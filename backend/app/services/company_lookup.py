"""Direct company lookup in the permitted public sources (Step 5.4): the company the user searched for, when
LeadFinder does not know it yet. Bounded by a deadline, stopping at the first strong entity; no paid API, no
search-engine page, never LinkedIn.

    1 local source corpus   directories, registers, associations, exhibitors already ingested (no request):
                            full-text narrowed, then the record's own name keys / domain must match the query;
                            the sources of the query's industry first (routed: 'hotel' -> hospitality sources)
    2 discovery extracts    Overture Maps, OpenStreetMap, official dataset files (cached; no request per query):
                            every named business, indexed once per process by name key and website domain
    3 GLEIF (live)          legal entities of another country ('... in Dubai'); Lebanon's are in the corpus
    4 web discovery         the company's own website found from its name (web_discovery: domain candidates,
                            a licensed search API when one is configured) and VERIFIED on the site itself
    5 Wikidata              the strictly resolved Lebanese entity (wikidata.entity_for, cached), last: rate-limited
    the website             a domain query: the site's own name, when the site names itself after its domain
Every network source sits behind a circuit breaker (web_discovery.Breaker): a failing source never blocks a search.

A candidate is STRONG when its name has the query's exact keys (legal form, word order, French / English forms
ignored) or its website is the queried domain; a spelling match only (skeleton, domain label) is POSSIBLE and is
never created automatically. Strong candidates go through discovery's own pipeline: validation, consolidation
(branches of one entity are one company), duplicate resolution against LeadFinder (domain, identifiers, phone +
name, name + city: an existing company is reused, never duplicated; a deleted one is never recreated), then
persistence with each source and its evidence.
"""

import copy
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass
from functools import lru_cache
from datetime import datetime
from typing import Callable
from urllib.parse import urlsplit

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import Company, ExternalDocument, Source
from app.services.discovery.candidate import CompanyCandidate, ConnectorConfig, SearchQuery
from app.services.discovery.consolidation import assess, consolidate
from app.services.discovery.deduplication import resolve
from app.services.discovery.geography import _fold, find_country
from app.services.discovery.industries import AnyBusinessProfile
from app.services.discovery.normalizer import normalize, validate
from app.services.discovery.persistence import save
from app.services.normalization import company_domain

logger = logging.getLogger("leadfinder.search")
EXTRACT_KINDS = ("overture", "osm", "dataset_file")
# the sector a curated source is about states the industry of the companies it lists (hospital syndicate...)
SECTOR_INDUSTRY = {"bank": "Financial Services", "insurance": "Insurance", "healthcare": "Healthcare",
                   "construction": "Construction", "manufacturing": "Manufacturing", "food": "Food Manufacturing",
                   "pharma": "Pharmaceutical", "technology": "Technology", "agriculture": "Agriculture"}
MAX_CANDIDATES = 8


@lru_cache(maxsize=400_000)
def _keys(name: str) -> frozenset[str]:
    """A source record's name keys, computed once per process (an extract's 50,000 names are read per lookup)."""
    from app.services.company_search import name_keys

    return frozenset(name_keys(name))


def _loose(key: str) -> str | None:
    """A name key of 2+ words without its vowels after each word's first letter: the transliteration variants
    ('malak tawook' / 'malak tawouk') share it. A spelling match only: POSSIBLE, never created."""
    words = key.split()
    if key[0] in "~^@%" or len(words) < 2:
        return None
    return "%" + " ".join(w[0] + re.sub(r"[aeiouy]", "", w[1:]) for w in words)


@lru_cache(maxsize=400_000)
def _unplaced(name: str) -> frozenset[str]:
    """A record's name keys without their place / country words ('... School Beirut' -> '... school')."""
    from app.services.company_search import _COUNTRY
    from app.services.people.external.lebanon.records import PLACES

    return frozenset(u for k in _keys(name) if k[0] not in "~^" and (
        u := " ".join(t for t in k.split() if t not in PLACES and t not in _COUNTRY)) and u != k)


def strength(name: str, q) -> str | None:
    """'strong' (the query's exact keys) / 'possible' (the same consonant skeleton) / None for a source record's
    name, or for a domain query, its domain label inside the name ('possible')."""
    if q.domain:
        label = q.domain.split(".")[0]
        return "possible" if len(label) >= 4 and label in "".join(name.lower().split()) else None
    keys = _keys(name)
    if keys & q.keys or _unplaced(name) & q.keys:  # 'American Community School Beirut' for its name
        return "strong"
    if keys & q.skeletons and any(len(k.split()) >= 2 for k in keys & q.skeletons):
        return "possible"
    return None


@dataclass
class Found:
    candidate: CompanyCandidate
    config: ConnectorConfig
    strength: str
    record: object | None = None  # the corpus Record (aliases are learned from it)


def _out(f: Found, confidence: str) -> dict:
    """A public-source candidate as offered to the user; 'payload' (stored with the lookup, never sent) lets the
    user's pick create it through the same pipeline."""
    c = f.candidate
    return {"company_id": None, "name": c.company_name, "city": c.city, "country": c.country,
            "industry": c.industry, "website": c.website, "source": f.config.label or f.config.key,
            "match_type": "source_" + f.strength, "confidence": confidence,
            "page_url": c.source_url if c.source_type == "public_web" else None,  # the platform page, to check first
            "payload": {"candidate": {**asdict(c), "observed_at": c.observed_at.isoformat()},
                        "config": {"key": f.config.key, "source_type": f.config.source_type,
                                   "quality": f.config.quality, "label": f.config.label}}}


def _from_payload(payload: dict) -> Found:
    data = dict(payload["candidate"])
    data["observed_at"] = datetime.fromisoformat(data["observed_at"])
    cfg = payload["config"]
    return Found(CompanyCandidate(**data), _config(cfg["key"], cfg["source_type"], cfg["quality"], cfg["label"]),
                 "strong")


def _config(key: str, source_type: str, quality: int, label: str) -> ConnectorConfig:
    return ConnectorConfig(key=key, kind="lookup", enabled=True, countries=(), priority=0, source_type=source_type,
                           quality=quality, label=label)


# ---- 1. the local source corpus ----------------------------------------------------------------------------------


def routed_sources(industry: str | None) -> set[str]:
    """The source pack entries about the query's industry ('Insurance' -> the ICC register...)."""
    from app.services.people.external.lebanon import pack

    sector = {"Financial Services": "bank", "Insurance": "insurance", "Healthcare": "healthcare",
              "Pharmaceutical": "pharma", "Construction": "construction", "Manufacturing": "manufacturing",
              "Food Manufacturing": "food", "Technology": "technology"}.get(industry or "")
    if not sector:
        return set()
    return {k for k, c in pack.configs().items() if sector in c.sectors}


def _corpus(db, q, industry: str | None = None) -> list[Found]:
    from app.services.people.external.lebanon import pack
    from app.services.people.external.lebanon.records import org_key

    text = q.domain.split(".")[0] if q.domain else q.raw
    tsq = func.websearch_to_tsquery("simple", text)
    rows = db.scalars(select(ExternalDocument).where(ExternalDocument.search_vector.op("@@")(tsq),
                                                     ExternalDocument.content.is_not(None))
                      .order_by(func.ts_rank(ExternalDocument.search_vector, tsq).desc()).limit(40)).all()
    configs = pack.configs()
    routed = routed_sources(industry)
    rows = sorted(rows, key=lambda r: (r.metadata_ or {}).get("source") not in routed)  # stable: rank kept
    out: list[Found] = []
    for row in rows:
        key = (row.metadata_ or {}).get("source")
        cfg = configs.get(key)
        if cfg is None or cfg.role != "directory" or cfg.access == "disabled":
            continue
        for i, record in enumerate(pack.parsed_records(row)):
            if record.person or not record.org:
                continue  # organisation records: a person's employer line names no company facts
            if q.domain:  # the record's own name must be the domain's ('kassatly.net': a Kassatly name)
                label = q.domain.split(".")[0]
                found = "strong" if any(company_domain(d) == q.domain for d in record.domains) and any(
                    label in "".join(n.lower().split()) for n in record.org) else None
            else:
                found = max((strength(n, q) or "" for n in record.org), key=lambda s: s == "strong") or None
            if not found:
                continue
            facts = record.facts or {}
            name = next((n for n in record.org if org_key(n)), record.org[0])
            sectors = [s for s in cfg.sectors if s != "*"]
            out.append(Found(CompanyCandidate(
                connector=f"lookup_{key}"[:60], source_name=cfg.name, source_type=cfg.source_type,
                company_name=name, external_id=next(iter((record.identifiers or {}).values()), None)
                or f"{row.id}:{i}", source_url=row.url, legal_name=facts.get("legal_name"),
                website=(record.domains or [None])[0], phone=facts.get("phone") or record.phone,
                email=facts.get("email"), country="Lebanon", city=facts.get("city"),
                industry=SECTOR_INDUSTRY.get(sectors[0]) if len(sectors) == 1 else None,
                address=facts.get("address"), raw_metadata={"name": name, "names": record.org,
                                                            "excerpt": (record.excerpt or "")[:400],
                                                            "publisher": cfg.name}),
                _config(f"lookup_{key}"[:60], cfg.source_type, cfg.quality, cfg.name), found, record))
            if len(out) >= 20:
                return out
    return out


# ---- 2. discovery extracts (Overture, OSM, dataset files) ----------------------------------------------------------


WIKIDATA_WAIT = 4  # seconds a search waits for its turn at Wikidata (rate-limited, shared by all searches)
_WIKIDATA_GATE = threading.BoundedSemaphore(2)
TIER_MIN_SECONDS = 3  # a tier is not started with less time than this left: the search ends, not times out
VERIFY_SECONDS = 8  # web discovery: the candidate sites' verification, together
INDEX_SECONDS = 6 * 3600  # the extracts change with a new release only
_INDEX: dict[str, tuple[float, dict[str, list]]] = {}
_INDEX_LOCK = threading.Lock()


def _extract_index(country) -> dict[str, list]:
    """Every named business of the country's cached extracts, by name key and by website domain: built once per
    process (a few seconds, under a lock: concurrent first lookups wait for one build), then each lookup is a
    dictionary read instead of a scan of 50,000 places."""
    from app.services.discovery.orchestrator import build_connectors

    code = country.code if country else ""
    with _INDEX_LOCK:
        cached = _INDEX.get(code)
        if cached and time.monotonic() - cached[0] < INDEX_SECONDS:
            return cached[1]
        index: dict[str, list] = {}
        for connector in build_connectors(country):
            if connector.config.kind not in EXTRACT_KINDS:
                continue
            try:
                result = connector.search_companies(SearchQuery(country=country, area=None,
                                                                industry=AnyBusinessProfile(), limit=10**6))
            except Exception:
                logger.exception("lookup index: %s could not be read", connector.config.key)
                continue
            for c in result.candidates:
                if c.rejected:
                    continue
                for key in _keys(c.company_name) | {_loose(k) for k in _keys(c.company_name)} - {None}:
                    index.setdefault(key, []).append((c, connector.config))
                if domain := company_domain(c.website):
                    index.setdefault(f"@{domain}", []).append((c, connector.config))
        _INDEX[code] = (time.monotonic(), index)
        return index


def warm(country: str = "Lebanon") -> None:
    """Builds the extract index in a background thread (API start), so the first search does not wait for it."""
    def build():
        try:
            _extract_index(find_country(country))
        except Exception:
            logger.exception("lookup index warm-up failed")
    threading.Thread(target=build, name="lookup-index", daemon=True).start()


_BRANCH_SEP = re.compile(r"\s+[-–—|]\s+")


def _head_keys(name: str) -> set[str]:
    """The keys of a record's own name: the part before ' - ' ('Crepaway - Le Mall' -> Crepaway), and the whole."""
    from app.services.company_search import name_keys
    from app.services.people.external.lebanon.records import org_key

    return name_keys(_BRANCH_SEP.split(name)[0]) | {org_key(name)}


def in_city(candidate, city: str | None) -> bool:
    """The record is in the city the user named ('Byblos (Jbeil)': either name), or does not say where it is."""
    if not city or not (candidate.city or candidate.address):
        return True
    where = _fold(f"{candidate.city or ''} {candidate.address or ''}")
    return any(n in where for n in (_fold(p).strip() for p in re.split(r"[()/,]", city)) if len(n) >= 3)


def _extracts(q, country) -> list[Found]:
    index = _extract_index(country)
    keys = [f"@{q.domain}"] if q.domain else [*q.keys, *q.skeletons, *filter(None, map(_loose, q.keys))]
    out: list[Found] = []
    seen: set[int] = set()
    for key in keys:
        for c, config in index.get(key, [])[:20]:
            if id(c) in seen:
                continue
            found = "strong" if q.domain or key in q.keys else strength(c.company_name, q) or (
                "possible" if key[0] == "%" else None)  # a spelling variant: offered, never created
            if found == "strong" and not q.domain and key not in _head_keys(c.company_name):
                found = "possible"  # 'Crepaway - Le Mall' searched as 'Le Mall': a branch's place, not its name
            if found:
                seen.add(id(c))
                out.append(Found(copy.copy(c), config, found))  # a copy: the pipeline marks its records
    return out


# ---- 3. Wikidata ---------------------------------------------------------------------------------------------------


def _wikidata(q, country) -> list[Found]:
    from app.services.people.external.lebanon import pack, wikidata

    probe = Company(name=q.raw, headquarters_country=country.name if country else None, domain=q.domain,
                    website=f"https://{q.domain}" if q.domain else None)
    if not _WIKIDATA_GATE.acquire(timeout=WIKIDATA_WAIT):
        raise BreakerOpen("wikidata busy")  # its polite rate limit is shared: a search never queues long for it
    try:
        with SessionLocal() as db, pack.api_client() as http:
            entity = wikidata.entity_for(db, http, probe, second_language=False)
            db.commit()  # the cached answers
    finally:
        _WIKIDATA_GATE.release()
    if not entity or entity.get("foreign_brand"):
        return []  # a foreign organisation's item is never the local company searched for
    labels = wikidata._labels(entity)
    name = next((n for n in labels if strength(n, q) == "strong"), labels[0] if labels else q.raw)
    sites = [c["mainsnak"].get("datavalue", {}).get("value") for c in entity.get("claims", {}).get("P856", [])]
    found = "strong" if entity.get("match", 0) >= 85 else "possible"
    return [Found(CompanyCandidate(
        connector="lookup_wikidata", source_name="Wikidata", source_type="open_dataset", company_name=name,
        external_id=entity["id"], source_url=f"https://www.wikidata.org/wiki/{entity['id']}",
        website=next((s for s in sites if isinstance(s, str)), None), country=country.name if country else None,
        raw_metadata={"name": name, "labels": labels[:10], "publisher": "Wikidata"}),
        _config("lookup_wikidata", "open_dataset", 70, "Wikidata"), found)]


# ---- 4. the website of a domain query -----------------------------------------------------------------------------


def _website(q, country) -> list[Found]:
    from app.services.enrichment import orchestrator as enrichment

    from app.services.enrichment.pages import parse

    page = enrichment.website_fetcher().get(f"https://{q.domain}/")
    if (page.status or 0) >= 400 or not page.html or company_domain(page.url) != q.domain:
        return []
    doc = parse(page.html, page.url)
    label = q.domain.split(".")[0]
    names = [n for n in (doc.meta.get("og:site_name"), *(i.get("name") for i in doc.jsonld
                                                          if isinstance(i.get("name"), str)), doc.title) if n]
    # the site's own name, only when it is the domain's name ('Kassatly Chtaura' on kassatly.net)
    name = next((n.split("|")[0].split(" - ")[0].strip() for n in names
                 if label in "".join(n.lower().split()) and len(n) <= 120), None)
    if not name:
        return []
    return [Found(CompanyCandidate(
        connector="lookup_website", source_name=f"{q.domain} (company website)", source_type="company_website",
        company_name=name, external_id=q.domain, source_url=page.url, website=page.url,
        country=country.name if country and q.domain.endswith(f".{country.code.lower()}") else None,
        raw_metadata={"name": name, "title": doc.title, "publisher": q.domain}),
        _config("lookup_website", "company_website", 80, q.domain), "strong")]


# ---- the lookup -----------------------------------------------------------------------------------------------------


def _sources(q, country, intent=None) -> list[list[tuple[str, Callable[[], list[Found]]]]]:
    """Tiers, cheapest first; a tier runs only while no strong entity is found (Wikidata is rate-limited: last)."""
    first = [("extracts", lambda: _extracts(q, country))]
    if q.domain:
        first.append(("website", lambda: _website(q, country)))
    elif country is None or country.code != "LB":
        first.append(("gleif", lambda: _gleif(q, intent)))
    tiers = [first]
    if not q.domain and q.keys:
        tiers.append([("web_discovery", lambda: web_search(q, country, intent))])
    if country is not None and country.code == "LB":
        tiers.append([("wikidata", lambda: _wikidata(q, country))])
    return tiers


def _guarded(name: str, fn: Callable[[], list[Found]]) -> Callable[[], list[Found]]:
    """The source behind its circuit breaker: skipped while open; its failures counted."""
    from app.services.web_discovery import Breaker

    breaker = Breaker(f"lookup:{name}")

    def call() -> list[Found]:
        if breaker.open():
            raise BreakerOpen(name)
        try:
            result = fn()
        except Exception:
            breaker.record(False)
            raise
        breaker.record(True)
        return result
    return call


class BreakerOpen(Exception):
    """The source failed repeatedly moments ago: skipped for a while."""


def _gleif(q, intent) -> list[Found]:
    """Legal entities (any country) whose legal name has the query's keys, in the named country when known."""
    from app.services.people.external.lebanon import pack
    from app.services.query_understanding import COUNTRY_TLD
    from app.services.people.external.search import cached_json

    code = (COUNTRY_TLD.get(intent.country or "") or "").upper() if intent else ""
    params = {"filter[fulltext]": q.raw, "page[size]": 10}
    if code:
        params["filter[entity.legalAddress.country]"] = code
    with SessionLocal() as db, pack.api_client() as http:
        def fetch():
            r = http.get("https://api.gleif.org/api/v1/lei-records", params=params, timeout=10)
            r.raise_for_status()
            return r.json().get("data", [])
        records, _ = cached_json(db, "gleif_lookup", f"{q.raw}|{code}", 7, fetch)
        db.commit()
    out = []
    for item in records:
        entity = (item.get("attributes") or {}).get("entity") or {}
        name = (entity.get("legalName") or {}).get("name")
        if not name or strength(name, q) != "strong":
            continue
        address = entity.get("legalAddress") or {}
        out.append(Found(CompanyCandidate(
            connector="lookup_gleif", source_name="GLEIF - Legal Entity Identifiers", source_type="open_dataset",
            company_name=name, external_id=item.get("id"), source_url=f"https://search.gleif.org/#/record/{item.get('id')}",
            legal_name=name, country=intent.country if intent and intent.country else address.get("country"),
            city=address.get("city"), address=", ".join(address.get("addressLines") or [])[:300] or None,
            registration_number=(entity.get("registeredAs") or None),
            raw_metadata={"name": name, "lei": item.get("id"), "publisher": "GLEIF"}),
            _config("lookup_gleif", "open_dataset", 85, "GLEIF"), "strong"))
    return out


_TITLE_PARTS = re.compile(r"\s+[|•·–—-]\s+|\s+\(@|\s*\|\s*")
_PLATFORM_WORDS = {"home", "facebook", "instagram", "photos", "videos", "about", "menu", "google maps", "tiktok",
                   "linkedin", "x", "twitter", "posts", "reviews", "contact"}


_POST = re.compile(r"/(?:reel|reels|p|posts|videos|photos|video|status|watch|stories|explore|hashtag|events|groups|"
                   r"search|sharer)/", re.IGNORECASE)  # a post, or a place / tag page: not the business's own page
_ARABIC = re.compile(r"[\u0600-\u06ff]")


def _page_name(title: str) -> str:
    """'Al Shayeb - Home | Facebook' -> 'Al Shayeb': the first part of a platform page's title."""
    title = re.sub(r"[\u200e\u200f\u202a-\u202e]", "", title or "")  # direction marks around Arabic
    parts = [p.strip() for p in _TITLE_PARTS.split(title) if p.strip()]
    return next((p for p in parts if _fold(p) not in _PLATFORM_WORDS), "")[:200]


def _profiles(q, pages, country_name) -> list[Found]:
    """The company's pages on platforms (Facebook, Instagram, Maps, directories) a web search found: offered with
    the page as the source, never created on their own (a search result is not a fact; the user's pick is the
    confirmation). Only a page whose title carries every word of the searched name (in Latin letters or in Arabic:
    'Jbeil Supermarket' is not 'Le Mall Jbeil'), and a page, never a single post / video or an article (a headline
    is a sentence, a business's page title is its name)."""
    from app.services.normalization import _NAME_STOP
    from app.services.people.external.lebanon.identity import _GENERIC_WORDS

    words = [w for w in _fold(q.normalized or q.raw).split() if len(w) >= 3]
    if all(w in _NAME_STOP or w in _GENERIC_WORDS for w in words):
        return []  # '4 M Group Sarl': only 'group' to look for, any group's page would match
    groups = [g for g in ([w for w in words if not _ARABIC.search(w)], [w for w in words if _ARABIC.search(w)]) if g]
    out = []
    for page in pages:
        url = page.page or page.url
        name = _page_name(page.title)
        title = _fold(re.sub(r"[\u064b-\u0652\u200e\u200f]", "", page.title or ""))  # Arabic vowel marks off
        if not name or len(name.split()) > 6 or not groups or _POST.search(urlsplit(url).path) or \
                not any(all(w in title for w in g) for g in groups) or \
                not any(w in _fold(name) for g in groups for w in g):  # 'Mapstr': the platform, not the company
            continue
        out.append(Found(CompanyCandidate(
            connector="lookup_web_page", source_name=f"{page.domain} (web search)", source_type="public_web",
            company_name=name, external_id=url[:300], source_url=url, country=country_name,
            raw_metadata={"title": page.title, "snippet": page.snippet, "publisher": page.domain,
                          "discovered_by": page.source}),
            _config("lookup_web_page", "public_web", 50, page.domain.removeprefix("www.")), "possible"))
    return out[:4]


def web_search(q, country, intent) -> list[Found]:
    """The company's own website from its name: candidates from the discovery providers, each verified on the site
    (name AND country); a verified site is a strong candidate, a site naming the company outside the country is
    never one."""
    from app.services import web_discovery

    country_name = country.name if country else (intent.country if intent else None)
    name = q.raw
    candidates = []
    for provider in web_discovery.providers():
        breaker = web_discovery.Breaker(f"discovery:{provider.key}")
        if breaker.open():
            continue
        try:
            candidates += provider.search_company(name, country=country_name, city=intent.city if intent else None,
                                                  industry=intent.industry if intent else None, limit=4)
            breaker.record(True)
        except Exception:
            breaker.record(False)
    unique = list({c.domain: c for c in candidates if not c.profile}.values())[:6]
    out: list[Found] = []
    pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="verify")  # sites verified in parallel
    futures = {pool.submit(web_discovery.verify, name, c.url, country=country_name): c for c in unique}
    done, _ = wait(futures, timeout=VERIFY_SECONDS)  # a site that does not answer is not waited for
    pool.shutdown(wait=False, cancel_futures=True)
    seen: set[str] = set()
    for future in sorted(done, key=lambda f: futures[f].rank):
        candidate = futures[future]
        try:
            v = future.result()
        except Exception:
            continue
        if v.status == "rejected" or v.domain in seen:
            continue
        seen.add(v.domain)
        out.append(Found(CompanyCandidate(
            connector="lookup_web", source_name=f"{v.domain} (company website)", source_type="company_website",
            company_name=v.site_name or name, external_id=v.domain, source_url=v.url, website=v.url,
            phone=v.phone, city=v.city, country=v.country,
            raw_metadata={"name": v.site_name, "publisher": v.domain, "discovered_by": candidate.source,
                          "verification": v.reason}),
            _config("lookup_web", "company_website", 80, v.domain), "strong" if v.status == "strong" else "possible"))
        if v.status == "strong":
            break  # the company's own verified site: the others are not needed
    if not any(f.strength == "strong" for f in out):  # its pages elsewhere (Facebook, a directory...): offered
        out += _profiles(q, [c for c in candidates if c.profile or c.domain not in seen], country_name)
    return out


def _foreign(name: str):
    """A country outside LeadFinder's discovery geography ('... in Dubai'): its name and ISO code only."""
    from app.services.discovery.geography import Country
    from app.services.query_understanding import COUNTRY_TLD

    return Country((COUNTRY_TLD.get(name) or "xx").upper(), name, (-180.0, -90.0, 180.0, 90.0))


def run(db, q, *, country: str | None, city: str | None, user_id: int | None, deadline: float,
        intent=None, offer: bool = False) -> dict:
    """offer: the strong entities are offered for the user to pick, never created (the database already holds
    companies that sound like the query)."""
    country_obj = find_country(country or "Lebanon") or _foreign(country)
    report: list[dict] = []
    found: list[Found] = []
    t = time.perf_counter()
    try:
        found += _corpus(db, q, intent.industry if intent else None) if country_obj and country_obj.code == "LB" \
            else []
        report.append({"source": "corpus", "status": "ok", "found": len(found),
                       "ms": int((time.perf_counter() - t) * 1000)})
    except Exception:
        db.rollback()
        logger.exception("lookup corpus failed")
        report.append({"source": "corpus", "status": "failed"})
    timed_out = False
    for tier in _sources(q, country_obj, intent):
        if timed_out or any(f.strength == "strong" and in_city(f.candidate, city) for f in found):
            break  # stop early: an earlier source already knows the entity
        if deadline - time.monotonic() < TIER_MIN_SECONDS:
            report += [{"source": name, "status": "skipped", "error": "NO_TIME_LEFT"} for name, _ in tier]
            break
        pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="lookup")
        futures = {pool.submit(_guarded(name, fn)): (name, time.perf_counter()) for name, fn in tier}
        done, pending = wait(futures, timeout=max(0.0, deadline - time.monotonic()))
        for future in done:
            name, t0 = futures[future]
            try:
                items = future.result()
                found += items
                report.append({"source": name, "status": "ok", "found": len(items)})
            except BreakerOpen as exc:
                report.append({"source": name, "status": "skipped",
                               "error": "BUSY" if "busy" in str(exc) else "CIRCUIT_OPEN"})
            except Exception as exc:
                logger.info("lookup source %s failed: %s", name, exc.__class__.__name__)
                report.append({"source": name, "status": "failed", "error": exc.__class__.__name__})
        for future in pending:  # never waited for beyond the deadline (left to finish in the background)
            timed_out = True
            report.append({"source": futures[future][0], "status": "timed_out"})
        pool.shutdown(wait=False, cancel_futures=True)
    strong = [f for f in found if f.strength == "strong" and (q.domain or in_city(f.candidate, city))] \
        if q.domain or q.keys else []  # another town than the one named: offered, never opened or created
    wanted_country = country_obj.name
    if wanted_country and q.domain is None:  # a name search stays in the searched country
        strong = [f for f in strong if (f.candidate.country or wanted_country) == wanted_country]
    if strong and not offer:
        return {**_create(db, strong, country_obj, user_id, city=city), "sources": report}
    seen: set[tuple] = set()
    candidates = []
    strong_ids = {id(f) for f in strong}
    for f in sorted(found, key=lambda f: id(f) not in strong_ids):  # stable; one line per name and city (map branches)
        if (k := (_fold(f.candidate.company_name), _fold(f.candidate.city or ""))) not in seen:
            seen.add(k)
            candidates.append(_out(f, "possible"))
    candidates = candidates[:MAX_CANDIDATES]
    status = "ambiguous" if candidates else ("timed_out" if timed_out else "not_found")
    return {"status": status, "company": None, "candidates": candidates, "match_type": None, "confidence": None,
            "sources": report}


def select_candidate(db, lookup, index: int, *, user_id: int | None) -> dict:
    """The user picked one public-source candidate of an ambiguous lookup: the human confirmation of the entity.
    Created (or reused) through the same pipeline: duplicate resolution included."""
    picks = [c for c in lookup.candidates if c.get("payload")]
    if not 0 <= index < len(picks):
        raise LookupError("no such candidate")
    found = _from_payload(picks[index]["payload"])
    country = find_country(found.candidate.country or lookup.country or "Lebanon")
    return _create(db, [found], country, user_id, picked=True)


def _known(db, group) -> dict | None:
    """The entity is already in LeadFinder under its exact name keys (no domain / city on record to let
    discovery's resolver see it: 'Bank of Beirut' searched as bankofbeirut.com.lb): reused, never duplicated.
    Several companies with those keys: ambiguous. A known company whose domain differs is another entity."""
    from app.services.company_search import name_keys, search, resolve as resolve_hits

    domain = next((company_domain(c.website) for c in group.records if c.website), None)
    hits = [h for h in search(db, group.name) if h.match_type in ("exact_name", "normalized_name", "exact_alias",
                                                                    "alias") and set(h.company.search_keys or [])
            & {k for k in name_keys(group.name) if k[0] not in "~^"}]  # the same name, never a sound-alike
    hits = [h for h in hits if not (domain and h.company.domain and h.company.domain != domain)]
    if not hits:
        return None
    outcome, chosen = resolve_hits(hits)
    if outcome == "found":
        return chosen[0]
    return {"status": "ambiguous", "company": None, "match_type": None, "confidence": None,
            "candidates": [h.out() for h in chosen]}


def _create(db, strong: list[Found], country, user_id: int | None, picked: bool = False,
            city: str | None = None) -> dict:
    """Strong source records -> one entity through discovery's pipeline (reused or created), or ambiguous."""
    from app.services.company_search import EXACT, STRONG, Hit
    from app.services.discovery.orchestrator import _LOCK_KEY, _too_weak
    from app.services.people.external.lebanon import identity

    by_candidate = {id(f.candidate): f for f in strong}
    for f in strong:
        validate(f.candidate)
    accepted = [f.candidate for f in strong if not f.candidate.rejected]
    groups = sorted(consolidate(accepted), key=lambda g: len(g.primary.name))  # the cleanest name first
    # the same exact name in several sources ('Kassatly Chtaura sal', 'Kassatly Chtaura - Solvid') is one entity,
    # unless a record says otherwise (another website, operator or legal form): merged, not offered twice
    for other in groups[1:]:
        if not any(groups[0].conflicts(r) for r in other.records):
            for r in other.records:
                groups[0].add(r, "name")
            groups.remove(other)
    if len(groups) > 1 and city:  # 'hotel called Aleph in Byblos': the city the user named settles it
        here = [g for g in groups if any(c.city and _fold(city.split(" (")[0]) in _fold(c.city) for c in g.records)]
        groups = here if len(here) == 1 else groups
    if len(groups) > 1:  # several distinct entities carry the name: the user picks, nothing is created
        return {"status": "ambiguous", "company": None, "match_type": None, "confidence": None, "candidates": [
            _out(by_candidate[id(g.primary)], "strong") for g in groups][:MAX_CANDIDATES]}
    if not groups:
        return {"status": "not_found", "company": None, "candidates": [], "match_type": None, "confidence": None}
    group = groups[0]
    known = _known(db, group)
    if isinstance(known, dict):
        return known  # several known companies carry the name: the user picks
    profile = AnyBusinessProfile()
    norms = {id(c): normalize(c, country, profile) for c in group.records}
    db.execute(select(func.pg_advisory_xact_lock(_LOCK_KEY)))  # one resolve-and-create at a time
    resolution = resolve(db, group, norms, country.code)
    if resolution.company is None and known is not None:
        # known under the exact name only (no domain / city on record): the source's facts complete it
        from app.services.discovery.deduplication import Resolution

        resolution = Resolution(company=known.company, via="name (direct search)")
    if resolution.suppressed and not picked:
        db.rollback()  # deleted on purpose: never re-created on its own, offered so the user may add it back
        out = _out(by_candidate[id(group.primary)], "possible")
        out["detail"] = "Deleted from LeadFinder earlier: add it again only if you need it"
        return {"status": "ambiguous", "company": None, "match_type": None, "confidence": None, "candidates": [out]}
    if resolution.suppressed:  # the user's explicit pick lifts that deletion (this entity's keys only)
        _unsuppress(db, group, norms, country.code)
        resolution = resolve(db, group, norms, country.code)
    assessment = assess(group)
    curated = any(by_candidate[id(c)].record is not None or c.connector == "lookup_gleif"  # a registry /
                  for c in group.records)  # association list, a legal-entity register (LEI)
    if resolution.company is None and not picked and not curated and _too_weak(group, norms, assessment):
        db.rollback()  # a name and a map pin only: offered, never created
        return {"status": "ambiguous", "company": None, "match_type": None, "confidence": None, "candidates": [
            _out(by_candidate[id(group.primary)], "possible")]}
    configs = {by_candidate[id(c)].config.key: by_candidate[id(c)].config for c in group.records}
    company, is_new = save(db, group=group, norms=norms, resolution=resolution, assessment=assessment,
                           country=country, configs=configs, versions={}, user_id=user_id)
    db.flush()
    stated = next((c.industry for c in group.records if c.connector.startswith("lookup_") and c.industry), None)
    if stated and company.industry in (None, "", "Other"):
        from app.services.discovery.persistence import _evidence

        company.industry = stated  # the curated source's own sector (its evidence below)
        for c in group.records:
            source = db.scalar(select(Source).where(Source.external_reference == (c.external_id or "")[:300] or None,
                                                    Source.source_type == c.source_type).limit(1))
            if source is not None and c.industry:
                _evidence(db, source, company, "industry", c.industry, by_candidate[id(c)].config.quality * 0.8)
    for c in group.records:  # the source's spellings (Arabic / French...) become the company's aliases
        f = by_candidate[id(c)]
        if f.record is not None:
            source_id = db.scalar(select(func.max(ExternalDocument.source_id)).where(
                ExternalDocument.url == c.source_url))
            identity.learn_aliases(db, company, f.record, source_id, 90)
    if is_new:
        from app.services import audit_service
        from app.services.audit_service import AuditAction

        audit_service.record(db, action=AuditAction.COMPANY_CREATED, user_id=user_id, entity_type="company",
                             entity_id=company.id, metadata={"via": "company_lookup",
                                                             "sources": sorted(configs)})
    db.commit()
    _learn_domains(db, company, group.records)
    db.commit()
    hit = Hit(company, ("source_domain" if group.primary.connector == "lookup_website" else "source_name")
              if is_new else "source_known", EXACT if is_new else STRONG, 90)
    return {"status": "created" if is_new else "found", "company": hit.out(), "candidates": [],
            "match_type": hit.match_type, "confidence": hit.confidence, "resolved_from": group.primary.connector}


def _unsuppress(db, group, norms, country_code: str) -> None:
    """The user picked a deleted company in a direct search: its suppression keys are lifted, so it is created."""
    from sqlalchemy import delete, tuple_

    from app.models import DiscoverySuppression
    from app.services.discovery.deduplication import identifiers

    keys = [k for c in group.records for k in identifiers(c, norms[id(c)], country_code)]
    keys += [("domain", n.domain) for c in group.records if (n := norms[id(c)]).domain]
    if keys:
        db.execute(delete(DiscoverySuppression).where(
            tuple_(DiscoverySuppression.scheme, DiscoverySuppression.value).in_(keys)))


def _learn_domains(db, company: Company, records) -> None:
    """Every website the sources give the entity becomes one of its domains (the next search by any of them is a
    database hit); a domain already another company's is left to it."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.models import CompanyDomain

    for c in records:
        domain = company_domain(c.website)
        if domain:
            status = "current" if company.domain in (None, domain) else "alternate"
            db.execute(pg_insert(CompanyDomain).values(company_id=company.id, domain=domain[:253], status=status)
                       .on_conflict_do_nothing(index_elements=["domain"]))
