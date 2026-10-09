"""Validation set and untouched final holdout for direct company search (Step 5.4.1).

    python -m scripts.search_holdout select                     # freeze both sets (once): disjoint from the dev set
    python -m scripts.search_holdout run validation LABEL       # may be inspected and tuned against
    python -m scripts.search_holdout run holdout LABEL          # run ONCE at the end; never tuned against

Built from four pools, every company chosen in a fixed pseudo-random order (md5 with a set-specific salt), never
by how easy it is, and never one of the development set (direct_search_set.json / direct_search_unknown_set.json):

    known        LeadFinder companies: exact, legal, brand, Arabic, French form, domain, URL, partial name, typo,
                 natural language (industry / city phrasing), brand + country, global brand
    corpus       organisations of the public-source corpus not in LeadFinder (directories, registers, associations)
    map          businesses of the Overture extract not in LeadFinder
    web          companies whose official domain a source states, searched with every source switched OFF for that
                 query (web_only): only finding and verifying the website itself can succeed
    ambiguous    a distinctive word several companies share: nothing may be opened
    nonexistent  invented company names: nothing may be created

Run against a disposable copy of the benchmark database (lookups create companies).
"""

import hashlib
import json
import re
import sys
from collections import Counter

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Company, CompanyAlias
from scripts.search_benchmark import BENCHMARKS, SET_FILE, UNKNOWN_FILE, _LEGAL_SUFFIX, _translated, _typo, run

VALIDATION_FILE = BENCHMARKS / "search_validation_v1.json"
HOLDOUT_FILE = BENCHMARKS / "search_holdout_v1.json"
_ARABIC = re.compile(r"[؀-ۿ]")
PHRASE = {"Hospitality": "hotel", "Manufacturing": "manufacturer", "Food Manufacturing": "food company",
          "Retail": "store", "Technology": "technology company", "Education": "school", "Healthcare": "hospital",
          "Financial Services": "bank", "Insurance": "insurance company", "Construction": "contractor",
          "Distribution": "distributor", "Pharmaceutical": "pharma company", "Professional Services": "consulting firm",
          "Real Estate": "real estate company", "Logistics": "logistics company", "Telecom": "telecom company",
          "Food & Beverage": "restaurant", "Automotive": "car dealer"}
INVENTED = ["Zorvek Plastics", "Quintrel Logistics", "Mavrosi Foods", "Talbrinex Consulting", "Orvanta Hotels",
            "Kelmidor Trading", "Vastrion Pharma", "Ulmerak Builders", "Prixolan Textiles", "Danvelo Tech"]


def _md5(value, salt: str) -> str:
    return hashlib.md5(f"{value}|{salt}".encode()).hexdigest()


def _used() -> tuple[set[int], set[str]]:
    dev = json.loads(SET_FILE.read_text(encoding="utf-8")) + json.loads(UNKNOWN_FILE.read_text(encoding="utf-8"))
    return {r["expected_id"] for r in dev if r.get("expected_id")}, {r["expected"].lower() for r in dev}


def _pools(db):
    from app.services.company_search import name_keys
    from app.services.discovery.geography import find_country
    from app.services.discovery.industries import AnyBusinessProfile
    from app.services.discovery.candidate import SearchQuery
    from app.services.discovery.orchestrator import build_connectors
    from app.services.normalization import company_domain
    from app.services.people.external.lebanon import pack

    used_ids, used_names = _used()
    companies = [c for c in db.scalars(select(Company)).all() if c.id not in used_ids]
    known_keys = set().union(*(set(c.search_keys or []) for c in db.scalars(select(Company))))
    corpus, web = [], []
    seen: set[str] = set()
    for key, cfg in pack.configs().items():
        if cfg.role != "directory":
            continue
        for _, records in pack._loaded(db, key):
            for r in records:
                name = next((n for n in r.org if not _ARABIC.search(n)), None) if r.org else None
                arabic = next((n for n in r.org if _ARABIC.search(n) and not re.search(r"[A-Za-z]", n)), None) \
                    if r.org else None
                if r.person or not (name or arabic):
                    continue
                label = name or arabic
                keys = {k for k in name_keys(label) if k[0] not in "~^"}
                if not keys or keys & known_keys or label.lower() in used_names or len(label) > 60 or \
                        label.lower() in seen:
                    continue
                seen.add(label.lower())
                row = {"name": name, "arabic": arabic, "source": key, "city": (r.facts or {}).get("city"),
                       "sector": next((s for s in cfg.sectors if s != "*"), None)}
                corpus.append(row)
                domain = next((d for d in (company_domain(x) for x in r.domains) if d), None)
                if domain and name:
                    web.append({**row, "domain": domain})
    lebanon = find_country("Lebanon")
    extract = []
    for connector in build_connectors(lebanon):
        if connector.config.kind != "overture":
            continue
        for c in connector.search_companies(SearchQuery(country=lebanon, area=None, industry=AnyBusinessProfile(),
                                                        limit=10 ** 6)).candidates:
            keys = {k for k in name_keys(c.company_name) if k[0] not in "~^"}
            if c.rejected or not keys or keys & known_keys or len(c.company_name.split()) < 2 or \
                    c.company_name.lower() in seen:
                continue
            seen.add(c.company_name.lower())
            extract.append({"name": c.company_name, "city": c.city, "industry": c.industry,
                            "domain": company_domain(c.website)})
            if company_domain(c.website):
                web.append({"name": c.company_name, "domain": company_domain(c.website), "source": "overture",
                            "city": c.city})
    return companies, corpus, extract, web


def _resolves(domain: str) -> bool:
    from app.services.discovery import fetch

    try:
        return any(fetch.is_public(a) for a in fetch.resolve(domain))
    except Exception:
        return False


def build(db, salt: str, plan: dict[str, int], taken: set) -> list[dict]:
    """One set; `taken` (company ids / names already used by another set) is updated."""
    from app.services.company_search import _core
    from app.services.people.external.lebanon.records import name_variants, org_key

    companies, corpus, extract, web = _pools(db)
    companies = sorted(companies, key=lambda c: _md5(c.id, salt))
    aliases: dict[int, list[str]] = {}
    for a in db.scalars(select(CompanyAlias)):
        aliases.setdefault(a.company_id, []).append(a.alias)
    out: list[dict] = []

    def latin(c):
        return next((v for v in name_variants(c.name) if not _ARABIC.search(v)), None)

    def take(kind: str, make, pool=None) -> None:
        n = plan.get(kind, 0)
        for c in pool if pool is not None else companies:
            if n <= 0:
                break
            ident = c.id if isinstance(c, Company) else c["name"] or c.get("arabic")
            if ident in taken:
                continue
            row = make(c)
            if row:
                out.append({"kind": kind, **row})
                taken.add(ident)
                n -= 1

    known = lambda q, c: {"query": q, "expected_id": c.id, "expected": c.name} if q else None  # noqa: E731
    take("exact", lambda c: known(c.name, c) if not _ARABIC.search(c.name) else None)
    take("legal", lambda c: known(_LEGAL_SUFFIX.sub("", c.name) if _LEGAL_SUFFIX.search(c.name) else
                                  f"{latin(c)} SAL" if latin(c) else None, c))

    def brand(c):
        name = latin(c)
        core = _core(org_key(name)) if name else None
        words = [w for w in (name or "").split() if org_key(w) and org_key(w) in (core or "").split()]
        return known(" ".join(words), c) if core and words and " ".join(words).lower() != name.lower() else None
    take("brand", brand)
    take("arabic", lambda c: known(next((v for v in [*name_variants(c.name), *aliases.get(c.id, [])]
                                         if _ARABIC.search(v) and not re.search(r"[A-Za-z]", v)), None), c))
    take("french", lambda c: known(_translated(latin(c)), c))
    take("domain", lambda c: known(c.domain, c))
    take("url", lambda c: known(f"https://{c.domain}/about" if c.domain else None, c))
    take("partial", lambda c: known(" ".join(latin(c).split()[:2]) if latin(c) and len(latin(c).split()) >= 3
                                    else None, c))
    take("typo", lambda c: known(_typo(latin(c)) if latin(c) else None, c))
    take("natural", lambda c: known(
        f"{PHRASE[c.industry]} called {latin(c)}" + (f" in {c.headquarters_city}" if c.headquarters_city else "")
        if latin(c) and c.industry in PHRASE else None, c))
    take("brand_country", lambda c: known(f"{latin(c)} Lebanon" if latin(c) and len(latin(c).split()) <= 2
                                          else None, c))
    corpus = sorted(corpus, key=lambda r: _md5(r["name"] or r["arabic"], salt))
    absent = lambda q, r: {"query": q, "expected_id": None, "expected": r["name"] or r["arabic"],  # noqa: E731
                           "source": r["source"]} if q else None
    take("corpus_name", lambda r: absent(_LEGAL_SUFFIX.sub("", r["name"]).strip() if r["name"] else None, r),
         corpus)
    take("corpus_natural", lambda r: absent(
        f"{ {'bank': 'bank', 'insurance': 'insurance company', 'healthcare': 'hospital', 'construction': 'contractor', 'manufacturing': 'factory', 'food': 'food company', 'pharma': 'pharma company', 'technology': 'technology company'}.get(r['sector'], 'company')} called {_LEGAL_SUFFIX.sub('', r['name']).strip()}"
        if r["name"] else None, r), corpus)
    take("corpus_typo", lambda r: absent(_typo(r["name"]) if r["name"] else None, r), corpus)
    take("corpus_arabic", lambda r: absent(r["arabic"] if r["arabic"] else None, r), corpus)
    extract = sorted(extract, key=lambda r: _md5(r["name"], salt))
    take("map_name", lambda r: {"query": r["name"], "expected_id": None, "expected": r["name"], "source": "overture"},
         extract)
    take("map_city", lambda r: {"query": f"{r['name']} in {r['city']}", "expected_id": None, "expected": r["name"],
                                "source": "overture"} if r["city"] and not _ARABIC.search(r["city"]) else None,
         extract)
    web = sorted(web, key=lambda r: _md5(r["domain"], salt))
    take("web", lambda r: {"query": _LEGAL_SUFFIX.sub("", r["name"]).strip(), "expected_id": None,
                           "expected": r["name"], "expected_domain": r["domain"], "web_only": True,
                           "source": r["source"]} if _resolves(r["domain"]) else None, web)
    words = Counter(w for c in companies for w in set(org_key(latin(c) or "").split()) if len(w) >= 5)
    shared = sorted((w for w, n in words.items() if n >= 2 and w not in {org_key(c.name) for c in companies}),
                    key=lambda w: _md5(w, salt))
    for w in shared[:plan.get("ambiguous", 0)]:
        if w not in taken:
            out.append({"kind": "ambiguous", "query": w.title(), "expected_id": None, "expected": "ambiguous"})
            taken.add(w)
    for name in [n for n in sorted(INVENTED, key=lambda n: _md5(n, salt)) if n not in taken][
            :plan.get("nonexistent", 0)]:
        out.append({"kind": "nonexistent", "query": name, "expected_id": None, "expected": "not_found"})
        taken.add(name)
    return out


HOLDOUT_PLAN = {"exact": 12, "legal": 8, "brand": 8, "arabic": 8, "french": 8, "domain": 8, "url": 6, "partial": 8,
                "typo": 10, "natural": 14, "brand_country": 5, "corpus_name": 20, "corpus_natural": 10,
                "corpus_typo": 5, "corpus_arabic": 9, "map_name": 15, "map_city": 10, "web": 25, "ambiguous": 8,
                "nonexistent": 7}
VALIDATION_PLAN = {k: max(1, v // 4) for k, v in HOLDOUT_PLAN.items()}
SAFETY_FILE = BENCHMARKS / "search_safety_v1.json"
# Step 6 gate: 50 new searches (none of dev / validation / holdout); invented names and web-only excluded
SAFETY_PLAN = {"exact": 5, "legal": 3, "brand": 3, "french": 3, "domain": 3, "url": 2, "partial": 3, "typo": 4,
               "natural": 5, "brand_country": 2, "corpus_name": 6, "corpus_natural": 3, "corpus_typo": 1,
               "map_name": 3, "map_city": 2, "ambiguous": 2}


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "run"
    if command == "select-safety":
        taken = set()
        for f in (HOLDOUT_FILE, VALIDATION_FILE):
            for r in json.loads(f.read_text(encoding="utf-8")):
                taken.add(r["expected_id"]) if r.get("expected_id") else None
                taken.add(r["expected"])
                taken.add(r["query"].lower())
        with SessionLocal() as db:
            safety = build(db, "safety-v1", SAFETY_PLAN, taken)
        SAFETY_FILE.write_text(json.dumps(safety, ensure_ascii=False, indent=1), encoding="utf-8")
        print("safety", len(safety), dict(Counter(r["kind"] for r in safety)))
    elif command == "select":
        taken: set = set()
        with SessionLocal() as db:
            holdout = build(db, "holdout-v1", HOLDOUT_PLAN, taken)  # first: the validation set never takes its rows
            validation = build(db, "validation-v1", VALIDATION_PLAN, taken)
        HOLDOUT_FILE.write_text(json.dumps(holdout, ensure_ascii=False, indent=1), encoding="utf-8")
        VALIDATION_FILE.write_text(json.dumps(validation, ensure_ascii=False, indent=1), encoding="utf-8")
        print("holdout", len(holdout), dict(Counter(r["kind"] for r in holdout)))
        print("validation", len(validation), dict(Counter(r["kind"] for r in validation)))
    else:
        which, label = sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "latest"
        rows = json.loads({"holdout": HOLDOUT_FILE, "safety": SAFETY_FILE}.get(which, VALIDATION_FILE)
                          .read_text(encoding="utf-8"))
        report = run(rows, label)
        (BENCHMARKS / f"search_{which}_result_{label}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(json.dumps(report["kpis"], indent=1))
