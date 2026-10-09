"""Direct company search (Step 5.4): a salesperson types the company they want (name, legal / brand / trading name,
Arabic / French / English name, domain or website URL) and LeadFinder resolves the ONE company it means: from its
own database first, then from the permitted public sources it already uses. Deterministic, evidence first: a
company is opened only on a strong match and created only on strong source evidence; anything less is offered as
possible matches, never guessed.

    query -> parse: a domain / URL -> its registrable domain; a name -> its keys (legal forms, word order,
             French / English word forms ignored: records.org_key), its consonant skeleton (Arabic ~ Latin, i ~ y
             typos: identity.skeleton), its normalized name (typos: trigram similarity)
          -> DATABASE (search): domain, identifier, exact name / legal name / alias, normalized keys,
             transliteration, containment, fuzzy -> candidates ranked, each with a match type and a confidence
                 EXACT     domain, identifier, the exact name / legal name / alias
                 STRONG    the same name up to legal form / word order / French-English forms; an Arabic <-> Latin
                           (or i/y) spelling of a name of 2+ distinctive words
                 POSSIBLE  one-word transliteration, a name contained in a longer one, a close spelling
                 WEAK      a distant spelling
          -> one EXACT / STRONG company (location context may break a tie): found, opened at once
             several: ambiguous, the user picks; POSSIBLE / WEAK alone: never opened automatically
          -> nothing strong: PUBLIC SOURCES (lookup), bounded (LOOKUP_SECONDS), stopping at the first strong entity:
             the local source corpus (directories, registers, associations: no request), Overture and
             OpenStreetMap (cached extracts), Wikidata (Lebanese entities only), the company's own website (a
             domain query) -> discovery's own validation, consolidation, duplicate resolution and persistence (one
             company per entity, with its sources and evidence) -> research queued (company -> people -> deep)
          -> every lookup recorded (company_lookups): analytics, a short-lived negative cache, and the external
             candidates of an ambiguous lookup, which the user can pick from (select)

Autocomplete (GET /companies/search) is the database search only: no public source is ever called per keystroke.
"""

import logging
import re
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Company, CompanyAlias, CompanyDomain, CompanyIdentifier, CompanyLookup
from app.services.discovery.geography import _fold, find_country
from app.services.normalization import company_domain, normalize_company_name

logger = logging.getLogger("leadfinder.search")

LOOKUP_SECONDS = 20  # the external lookup's hard deadline (company research continues on its own afterwards)
NEGATIVE_HOURS = 24  # a query that found nothing is not researched again for this long
DIRECT_LOOKUP = 3  # job priority of the research of a company the user just searched for (opened: 5)
MAX_RESULTS = 8
TYPO_SIMILARITY = 0.75
CLOSE_SPELLING = 0.9  # a longer name typed with a slip opens the company when nothing else is close  # a one-word typo opens the company only when it is the only one that sounds the same
EXACT, STRONG, POSSIBLE, WEAK = "exact", "strong", "possible", "weak"
_ORDER = {EXACT: 0, STRONG: 1, POSSIBLE: 2, WEAK: 3}
_ARABIC = re.compile(r"[؀-ۿ]")
_DOMAIN = re.compile(r"^(https?://)?(www\.)?[a-z0-9-]+(\.[a-z0-9-]+)+(/\S*)?$", re.IGNORECASE)


# ---- keys -----------------------------------------------------------------------------------------------------------


def skeleton_key(name: str) -> str | None:
    """The consonant skeletons of a name's distinctive words, order-free: 'Kassatly Chtaura' / 'Kassatli
    Chtaura' / 'كساتلي شتورا' -> the same key (generic and sector words dropped). None: nothing distinctive."""
    from app.services.people.external.lebanon.identity import _name_skeletons

    skeletons = _name_skeletons(name)
    return " ".join(sorted(skeletons)) if skeletons else None


def _core(key: str) -> str | None:
    """The distinctive part of a name key ('blom bank' -> 'blom'), when it can stand for the company alone."""
    from app.services.people.external.lebanon.identity import _AR_GENERIC, _GENERIC_WORDS
    from app.services.people.external.lebanon.records import _SECTOR, PLACES

    tokens = [t for t in key.split() if t not in _SECTOR and t not in PLACES and _fold(t) not in _GENERIC_WORDS
              and t not in _AR_GENERIC and t not in _CORE_GENERIC]
    core = " ".join(tokens)
    return core if core and core != key and len(core) >= 4 else None


_COUNTRY = {"lebanon", "liban", "lebanese", "libanaise", "لبنان"}
_CORE_GENERIC = {"credit", "capital", "investment", "private", "commercial", "central", "first", "new",
                 "modern", "united", "royal", "grand", "plaza", "palace", "city", "park", "house", "home",
                 "design", "art", "arts", "style", "fashion", "beauty", "care", "health", "life"}


def _generic_only(key: str) -> bool:
    from app.services.people.external.lebanon.identity import _AR_GENERIC, _GENERIC_WORDS
    from app.services.people.external.lebanon.records import _SECTOR
    from app.services.query_understanding import INDUSTRY_WORDS

    return all(_fold(t) in _GENERIC_WORDS or t in _AR_GENERIC or t in _SECTOR or t in _CORE_GENERIC
               or _fold(t) in INDUSTRY_WORDS or t in ("center", "centre", "village", "house", "office", "studio")
               for t in key.split())


def name_keys(*names: str | None) -> set[str]:
    """The search keys of a company's names: org keys of every variant ('X SAL - شركة X' -> both parts),
    '~'-prefixed skeleton keys and '^'-prefixed distinctive cores ('BLOM Bank' -> '^blom')."""
    from app.services.people.external.lebanon.records import name_variants, org_key

    from app.services.people.external.lebanon.records import PLACES

    keys: set[str] = set()
    for name in filter(None, names):
        for variant in name_variants(name):
            key = org_key(variant)
            if all(t in PLACES or t in _COUNTRY for t in key.split()):
                continue  # 'Lebanon' in 'National Bank of Kuwait (Lebanon)', 'Byblos Company'
            if _generic_only(key):
                continue  # 'Center for', 'Consulting Center': words, not a name ('S.A.S Center' is not them)
            if len(key) >= 2:
                keys.add(key[:200])
                if core := _core(key):
                    keys.add(f"^{core}"[:200])
            if sk := skeleton_key(variant):
                keys.add(f"~{sk}"[:200])
    return keys


def company_keys(company: Company) -> list[str]:
    return sorted(name_keys(company.name, company.legal_name))


@dataclass
class Query:
    raw: str
    domain: str | None = None
    keys: set[str] = field(default_factory=set)  # org keys
    skeletons: set[str] = field(default_factory=set)  # '~' keys
    cores: set[str] = field(default_factory=set)  # '^' keys: the query as a company's distinctive core
    unplaced: set[str] = field(default_factory=set)  # keys without the query's place words ('Nike Lebanon')
    query_cores: set[str] = field(default_factory=set)  # '^' keys of the query's own distinctive part
    normalized: str = ""
    exact: str = ""  # case / space folded raw text


def parse(raw: str) -> Query:
    raw = " ".join((raw or "").split())[:200]
    q = Query(raw=raw, exact=_fold(raw).strip())
    if " " not in raw and _DOMAIN.match(raw) and (domain := company_domain(raw)):
        q.domain = domain
        return q
    keys = name_keys(raw)
    q.keys = {k for k in keys if k[0] not in "~^"}
    q.skeletons = {k for k in keys if k.startswith("~")}
    q.cores = {f"^{k}" for k in q.keys}  # the whole query as a brand ('BLOM')
    q.query_cores = {f"^{c}" for k in q.keys if (c := _core(k))}  # its distinctive part ('Movenpick Hotel Beirut')
    from app.services.people.external.lebanon.records import PLACES

    places = PLACES | _COUNTRY
    q.unplaced = {u for k in q.keys if (u := " ".join(t for t in k.split() if t not in places)) and u != k} - q.keys
    q.normalized = normalize_company_name(raw) or raw.lower()
    return q


# ---- database search ------------------------------------------------------------------------------------------------


@dataclass
class Hit:
    company: Company
    match_type: str
    confidence: str
    score: float
    detail: str = ""
    similarity: float = 0.0  # spelling similarity of the normalized names (typos)

    def out(self) -> dict:
        c = self.company
        return {"company_id": c.id, "name": c.name, "legal_name": c.legal_name, "city": c.headquarters_city,
                "country": c.headquarters_country, "industry": c.industry, "website": c.website, "domain": c.domain,
                "match_type": self.match_type, "confidence": self.confidence, "detail": self.detail}


def search(db: Session, raw: str, *, country: str | None = None, city: str | None = None,
           industry: str | None = None, limit: int = MAX_RESULTS) -> list[Hit]:
    """LeadFinder's own companies matching the query, best first (database only: never a network call)."""
    q = parse(raw)
    hits: dict[int, Hit] = {}

    def add(company: Company, match_type: str, confidence: str, score: float, detail: str = "") -> None:
        old = hits.get(company.id)
        if old is None or score > old.score:
            hits[company.id] = Hit(company, match_type, confidence, score, detail)

    if q.domain:
        for c in db.scalars(select(Company).where(Company.domain == q.domain)):
            add(c, "domain", EXACT, 100, q.domain)
        for c in db.scalars(select(Company).join(CompanyIdentifier, CompanyIdentifier.company_id == Company.id)
                            .where(CompanyIdentifier.scheme == "web", CompanyIdentifier.value == q.domain)):
            add(c, "domain", EXACT, 99, q.domain)
        for c, status in db.execute(select(Company, CompanyDomain.status).join(
                CompanyDomain, CompanyDomain.company_id == Company.id).where(CompanyDomain.domain == q.domain)):
            add(c, "domain" if status == "current" else f"{status}_domain", EXACT, 98, q.domain)  # former domains
        label = q.domain.split(".")[0]
        if len(label) >= 4:  # the name behind a domain not on record: 'kassatly.net' -> companies named Kassatly
            for c in db.scalars(select(Company).where(Company.normalized_name.op("%")(label)).limit(20)):
                if label in (c.normalized_name or "").replace(" ", ""):
                    add(c, "domain_label", POSSIBLE, 55, label)
    else:
        if q.raw:
            for c in db.scalars(select(Company).join(CompanyIdentifier, CompanyIdentifier.company_id == Company.id)
                                .where(CompanyIdentifier.value == q.raw, CompanyIdentifier.scheme != "web").limit(5)):
                add(c, "identifier", EXACT, 98, q.raw)
        all_keys = list(q.keys | q.skeletons | q.cores | q.unplaced | q.query_cores)
        if all_keys:
            for c in db.scalars(select(Company).where(Company.search_keys.overlap(all_keys)).limit(50)):
                names = [n for n in (c.name, c.legal_name) if n]
                own = set(c.search_keys or [])
                if any(_fold(n).strip() == q.exact for n in names):
                    add(c, "exact_name", EXACT, 96)
                elif own & q.keys:
                    add(c, "normalized_name", STRONG, 90)
                elif own & q.unplaced:  # 'Nike Lebanon' -> 'Nike', 'Le Gray Beirut' -> 'Le Gray'
                    add(c, "name_without_place", STRONG, 86)
                elif own & q.cores:
                    add(c, "brand_core", STRONG, 84, next(iter(own & q.cores))[1:])
                elif own & q.query_cores:  # the same distinctive name, generic / place words aside
                    add(c, "name_core", STRONG, 82, next(iter(own & q.query_cores))[1:])
                else:
                    sk = next(iter(set(c.search_keys or []) & q.skeletons))
                    strong = len(sk.split()) >= 2
                    sim = SequenceMatcher(None, q.normalized, c.normalized_name or "").ratio()
                    add(c, "transliteration", STRONG if strong else POSSIBLE, (80 if strong else 62) + 10 * sim, sk[1:])
                    hits[c.id].similarity = sim
            for alias, c in db.execute(select(CompanyAlias, Company).join(Company, Company.id == CompanyAlias.company_id)
                                       .where(or_(CompanyAlias.normalized_alias.in_(list(q.keys) or [""]),
                                                  CompanyAlias.skeleton_key.in_([k[1:] for k in q.skeletons] or [""])))
                                       .limit(50)):
                if _fold(alias.alias).strip() == q.exact:
                    add(c, "exact_alias", EXACT, 94, alias.alias)
                elif alias.normalized_alias in q.keys:
                    add(c, "alias", STRONG, 88, alias.alias)
                else:
                    strong = len((alias.skeleton_key or "").split()) >= 2
                    add(c, "alias_transliteration", STRONG if strong else POSSIBLE, 78 if strong else 60, alias.alias)
        if len(q.normalized) >= 3:
            # a name inside a longer one ('Chtaura' / 'Kassatly Chtaura'): suggestions only
            words = q.normalized.split()
            pattern = "%" + "%".join(words) + "%"
            for c in db.scalars(select(Company).where(Company.normalized_name.like(pattern)).limit(20)):
                if c.id not in hits:
                    add(c, "contains", POSSIBLE, 58 if c.normalized_name.startswith(q.normalized) else 55)
            # typos: trigram similarity of the normalized names (and aliases)
            sim = func.similarity(Company.normalized_name, q.normalized)
            for c, s in db.execute(select(Company, sim).where(Company.normalized_name.op("%")(q.normalized))
                                   .order_by(sim.desc()).limit(10)):
                add(c, "fuzzy", POSSIBLE if s >= 0.6 else WEAK, 30 + 30 * s, f"similarity {s:.2f}")
            asim = func.similarity(CompanyAlias.normalized_alias, q.normalized)
            for alias, c, s in db.execute(select(CompanyAlias, Company, asim)
                                          .join(Company, Company.id == CompanyAlias.company_id)
                                          .where(CompanyAlias.normalized_alias.op("%")(q.normalized))
                                          .order_by(asim.desc()).limit(10)):
                add(c, "fuzzy_alias", POSSIBLE if s >= 0.6 else WEAK, 28 + 30 * s, alias.alias)
    if not q.domain:
        from app.services.web_discovery import _names_company

        arabic = bool(_ARABIC.search(q.raw))
        for cid, h in list(hits.items()):
            h.similarity = max(h.similarity, SequenceMatcher(None, q.normalized, h.company.normalized_name or "")
                               .ratio())
            if h.match_type == "transliteration" and h.confidence == POSSIBLE and not arabic and h.similarity < 0.5:
                del hits[cid]  # 'Kabbara' sounds like 'Cyberia' (k-b-r): noise, not a candidate
            elif h.match_type == "contains" and _names_company(h.company.name, q.raw):
                h.match_type, h.confidence, h.score = "name_prefix", STRONG, 83  # 'Oui Oui' -> 'Oui Oui Nursery'
    country_name = (find_country(country).name if country and find_country(country) else country)
    for h in hits.values():  # context: a weak ranking signal, never above a stronger identifier
        c = h.company
        if country_name and (c.headquarters_country or "").lower() == country_name.lower():
            h.score += 3
        if city and _fold(city) in _fold(" ".join(filter(None, (c.headquarters_city, c.headquarters_region)))):
            h.score += 4
        if industry and _fold(industry) in _fold(c.industry or ""):
            h.score += 1
    return sorted(hits.values(), key=lambda h: (_ORDER[h.confidence], -h.score, h.company.name))[:limit]


_NAME_TYPES = ("exact_name", "exact_alias", "normalized_name", "alias", "name_without_place")


def resolve(hits: list[Hit], *, country: str | None = None, city: str | None = None) -> tuple[str, list[Hit]]:
    """('found', [hit]) for one EXACT / STRONG company; ('ambiguous', hits) for several (location context may
    leave one); ('possible', hits) for POSSIBLE / WEAK only; ('none', [])."""
    strong = [h for h in hits if h.confidence in (EXACT, STRONG)]
    sounds = [h for h in hits if h.match_type == "transliteration"]
    if not strong and len(sounds) == 1 and sounds[0].similarity >= TYPO_SIMILARITY and not _ARABIC.search(
            sounds[0].company.name):
        # one company sounds like the query and it is spelled almost the same ('Nspresso', 'MobyNet'): a typo
        sounds[0].match_type, sounds[0].confidence = "typo", STRONG
        return "found", sounds
    close = [h for h in hits if h.similarity >= 0.8]
    if not strong and len(close) == 1 and close[0].similarity >= CLOSE_SPELLING and             len(close[0].company.normalized_name.split()) >= 2:
        # one company spelled almost exactly as typed, nothing else close ('Makassed Nursing Universiti')
        close[0].match_type, close[0].confidence = "typo", STRONG
        return "found", close
    if not strong:
        return ("possible", hits) if hits else ("none", [])
    best = [h for h in strong if h.confidence == strong[0].confidence]
    if best[0].match_type in _NAME_TYPES:  # the same name up to legal form: 'ABC Trading' / 'ABC Trading SARL'
        best = [h for h in strong if h.match_type in _NAME_TYPES]
    if len(best) == 1 and best[0].match_type in ("brand_core", "name_core", "name_prefix"):
        # a brand alone ('Ramada'): only when no other company carries it ('Ramada by Wyndham')
        others = [h for h in hits if h is not best[0] and h.match_type in ("contains", "brand_core", "name_core",
                                                                          "name_prefix", "transliteration")]
        if others:
            return "ambiguous", best + others
    if len(best) == 1:
        return "found", best
    for wanted, value in (("city", city), ("country", country)):
        if not value:
            continue
        country_name = find_country(value).name if wanted == "country" and find_country(value) else value
        here = [h for h in best if _fold(value if wanted == "city" else country_name) in _fold(
            " ".join(filter(None, (h.company.headquarters_city, h.company.headquarters_region)))
            if wanted == "city" else (h.company.headquarters_country or ""))]
        if len(here) == 1:
            here[0].detail = f"{here[0].detail} (only one in {value})".strip()
            return "found", here
    return "ambiguous", best


# ---- one lookup -------------------------------------------------------------------------------------------------------


_FROM = {"domain": "DOMAIN", "historical_domain": "DOMAIN", "alternate_domain": "DOMAIN", "identifier": "DB",
         "exact_alias": "ALIAS", "alias": "ALIAS", "alias_transliteration": "ALIAS"}
_SOURCE_FROM = {"lookup_web": "WEB_DISCOVERY", "lookup_website": "WEBSITE", "lookup_wikidata": "WIKIDATA",
                "lookup_gleif": "GLEIF", "overture": "MAP", "osm": "MAP"}
_CATEGORY_FROM = {"government": "GOVERNMENT", "licensed_directory": "GOVERNMENT", "association": "ASSOCIATION",
                  "open_dataset": "REGULATOR", "event": "ASSOCIATION", "conference": "ASSOCIATION"}


def lookup(db: Session, raw: str, *, user_id: int | None, country: str | None = "Lebanon", city: str | None = None,
           industry: str | None = None, external: bool = True) -> dict:
    """The explicit Search: the user's words understood (query_understanding), LeadFinder's database first (the
    words as typed, then the company name they contain, with its place / industry as context), then the public
    sources (bounded); creates the company on strong evidence and queues its research. Always ends in found /
    created / ambiguous / not_found / timed_out."""
    from app.services import query_understanding

    started = time.perf_counter()
    intent = query_understanding.parse(raw, country=country)
    country = intent.country or country
    city, industry = city or intent.city, industry or intent.industry
    names = query_understanding.names(intent)
    q = parse(intent.domain or (names[0] if names else raw))
    context = "|".join(_fold(x) for x in (city or "", industry or ""))
    record = CompanyLookup(query=raw[:200], user_id=user_id, country=country, city=city, status="searching_db",
                           parsed=intent.to_json(), normalized_query=(
                               (q.domain or " ".join(sorted(q.keys)) or q.normalized) + (f"|{context}" if context.strip("|")
                                                                                          else ""))[:200])
    hits = search(db, raw, country=country, city=city, industry=industry)
    outcome, chosen = resolve(hits, country=country, city=city)
    for name in names:  # 'hotel called Aleph in Byblos' -> 'Aleph', in Byblos
        if outcome == "found" or _fold(name) == _fold(raw):
            continue
        more = search(db, name, country=country, city=city, industry=industry)
        found_more, chosen_more = resolve(more, country=country, city=city)
        if found_more == "found" or (found_more == "ambiguous" and outcome != "ambiguous"):
            hits, outcome, chosen = more, found_more, chosen_more
    result: dict = {"query": raw, "status": None, "company": None, "candidates": [], "match_type": None,
                    "confidence": None, "external_used": False, "sources": [], "created": False,
                    "parsed": intent.to_json(), "resolved_from": None, "failure_reason": None}
    if outcome == "found":
        result.update(status="found", company=chosen[0].out(), match_type=chosen[0].match_type,
                      confidence=chosen[0].confidence, resolved_from=_FROM.get(chosen[0].match_type, "DB"))
    elif outcome == "ambiguous":
        result.update(status="ambiguous", candidates=[h.out() for h in chosen])
    elif external and not q.domain and len(q.normalized.split()) == 1 and             [h for h in hits if h.match_type in ("contains", "brand_core", "name_core", "name_prefix")]:
        # one word ('ACT', 'Village') that several known names contain: offered, never researched into a new company
        result.update(status="ambiguous", candidates=[h.out() for h in hits if h.confidence != WEAK],
                      failure_reason="AMBIGUOUS")
    elif external and (q.domain or q.keys):
        cached = _negative(db, record)
        if cached:
            result.update(status="not_found", candidates=[h.out() for h in hits], cached=True)
        else:
            from app.services import company_lookup

            result["external_used"] = True
            deadline = time.monotonic() + LOOKUP_SECONDS
            found = company_lookup.run(db, q, intent=intent, country=country, city=city, user_id=user_id,
                                       deadline=deadline)
            for name in names[1:]:  # the core name ('Hotel Albergo' -> 'Albergo') when the full one found nothing
                if found["status"] != "not_found" or time.monotonic() > deadline - 2:
                    break
                found = company_lookup.run(db, parse(name), intent=intent, country=country, city=city,
                                           user_id=user_id, deadline=deadline)
            result["sources"] = found["sources"]
            if found["status"] in ("found", "created"):
                result.update(status=found["status"], company=found["company"], match_type=found["match_type"],
                              confidence=found["confidence"], created=found["status"] == "created",
                              resolved_from=_resolved_from(found.get("resolved_from")))
            elif found["status"] == "ambiguous" or [h for h in hits if h.confidence != WEAK]:
                hits = [h for h in hits if h.confidence != WEAK]  # a distant spelling is not a candidate
                result.update(status="ambiguous", candidates=[h.out() for h in hits] + found["candidates"],
                              failure_reason="AMBIGUOUS" if found["status"] == "ambiguous" else "WEAK_EVIDENCE")
            else:
                statuses = {s["status"] for s in found["sources"]}
                result.update(status=found["status"], failure_reason=(  # not_found / timed_out
                    "SOURCE_TIMEOUT" if "timed_out" in statuses else
                    "WEB_DISCOVERY_FAILED" if any(s["source"] == "web_discovery" and s["status"] != "ok"
                                                  for s in found["sources"]) else "NO_SOURCE_RESULT"))
    else:
        result.update(status="ambiguous" if hits else "not_found", candidates=[h.out() for h in hits],
                      failure_reason="WEAK_EVIDENCE" if hits else "NO_LOCAL_MATCH")
    if result["company"]:
        from app.services.people import orchestrator as people

        company = db.get(Company, result["company"]["company_id"])
        people.request_research(db, company, DIRECT_LOOKUP, user_id=user_id)  # only what is due (stale)
    record.status = result["status"]
    record.result_company_id = (result["company"] or {}).get("company_id")
    record.match_type, record.confidence = result["match_type"], result["confidence"]
    record.result_count = 1 if result["company"] else len(result["candidates"])
    record.external_used, record.company_created = result["external_used"], result["created"]
    record.sources = result["sources"]
    record.candidates = [dict(c) for c in result["candidates"] if c.get("payload")]  # pickable (kept with payload)
    record.resolved_from, record.failure_reason = result["resolved_from"], result["failure_reason"]
    pick = 0
    for c in result["candidates"]:  # the user's pick refers to them by position (their payload is never sent)
        if c.pop("payload", None) is not None:
            c["pick_index"], pick = pick, pick + 1
    record.duration_ms = int((time.perf_counter() - started) * 1000)
    db.add(record)
    db.commit()
    result["lookup_id"], result["duration_ms"] = record.id, record.duration_ms
    logger.info("lookup=%s user=%s query=%r normalized=%r country=%s status=%s company=%s match=%s/%s "
                "db_candidates=%s external=%s sources=%s created=%s duration_ms=%s", record.id, user_id, q.raw,
                record.normalized_query, country, record.status, record.result_company_id, record.match_type,
                record.confidence, len(hits), record.external_used,
                ",".join(f"{s['source']}:{s['status']}" for s in result["sources"]), record.company_created,
                record.duration_ms)
    return result


def select_candidate(db: Session, lookup_id: int, index: int, *, user_id: int | None) -> dict:
    """The user's pick among an ambiguous lookup's public-source candidates."""
    from app.services import company_lookup
    from app.services.people import orchestrator as people

    started = time.perf_counter()
    lookup = db.get(CompanyLookup, lookup_id)
    if lookup is None or lookup.user_id not in (None, user_id):
        raise LookupError("no such lookup")
    found = company_lookup.select_candidate(db, lookup, index, user_id=user_id)
    if found.get("company"):
        company = db.get(Company, found["company"]["company_id"])
        people.request_research(db, company, DIRECT_LOOKUP, user_id=user_id)
        lookup.status, lookup.result_company_id = "selected", company.id
        lookup.company_created = lookup.company_created or found["status"] == "created"
        db.commit()
    for c in found.get("candidates", []):
        c.pop("payload", None)
    return {"query": lookup.query, "status": found["status"], "company": found.get("company"),
            "candidates": found.get("candidates", []), "match_type": found.get("match_type"),
            "confidence": found.get("confidence"), "external_used": True, "sources": [],
            "created": found["status"] == "created", "lookup_id": lookup.id,
            "duration_ms": int((time.perf_counter() - started) * 1000)}


def _resolved_from(connector: str | None) -> str:
    """Which kind of source established a company found / created by the public-source lookup."""
    if not connector:
        return "LOCAL_CORPUS"
    if connector in _SOURCE_FROM:
        return _SOURCE_FROM[connector]
    from app.services.people.external.lebanon import pack

    cfg = pack.configs().get(connector.removeprefix("lookup_"))
    return f"LOCAL_CORPUS:{_CATEGORY_FROM.get(cfg.source_type, 'SOURCE') if cfg else 'SOURCE'}"


def _negative(db: Session, record: CompanyLookup) -> bool:
    """The same query (and country, city, industry) found nothing in the public sources moments ago: not
    researched again, unless something it depends on changed since (a source ingested, an alias learned)."""
    from app.models import ExternalDocument

    since = datetime.now(timezone.utc) - timedelta(hours=NEGATIVE_HOURS)
    changed = max(filter(None, (db.scalar(select(func.max(ExternalDocument.created_at))),
                                db.scalar(select(func.max(CompanyAlias.created_at))))), default=None)
    if changed and changed > since:
        since = changed
    return bool(db.scalar(select(func.count()).select_from(CompanyLookup).where(
        CompanyLookup.normalized_query == record.normalized_query, CompanyLookup.country.is_not_distinct_from(
            record.country), CompanyLookup.external_used.is_(True), CompanyLookup.status == "not_found",
        CompanyLookup.created_at > since)))


def reindex(db: Session) -> dict:
    """Recomputes every company's search keys and every alias's keys (after a change to the name-key rules)."""
    from app.services.people.external.lebanon.records import org_key

    companies = aliases = 0
    for company in db.scalars(select(Company)):
        keys = company_keys(company)
        if keys != list(company.search_keys or []):
            company.search_keys, companies = keys, companies + 1
    seen: set[tuple[int, str]] = set()
    for alias in db.scalars(select(CompanyAlias).order_by(CompanyAlias.is_manual.desc(), CompanyAlias.id)):
        key, sk = org_key(alias.alias)[:300], (skeleton_key(alias.alias) or "")[:300] or None
        if (alias.company_id, key) in seen:
            db.delete(alias)  # two spellings now one key: the manual / first one is kept
            continue
        seen.add((alias.company_id, key))
        if (alias.normalized_alias, alias.skeleton_key) != (key, sk):
            alias.normalized_alias, alias.skeleton_key, aliases = key, sk, aliases + 1
    db.commit()
    return {"companies": companies, "aliases": aliases}


if __name__ == "__main__":  # python -m app.services.company_search reindex
    import sys

    from app.db.session import SessionLocal

    if sys.argv[1:] == ["reindex"]:
        with SessionLocal() as session:
            print(reindex(session))
