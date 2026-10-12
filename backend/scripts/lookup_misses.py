"""Unknown-company lookup measurement: real companies LeadFinder does not hold yet, through the real lookup.

    python -m scripts.lookup_misses check          # which queries the database already resolves (drop those)
    python -m scripts.lookup_misses run LABEL      # lookup each -> benchmarks/lookup_misses_LABEL.json

Run against a disposable copy of the database (a lookup creates companies), e.g.
    DATABASE_URL=postgresql+psycopg://...@db:5432/lookup_bench python -m scripts.lookup_misses run before
"""

import json
import statistics
import sys
import time
from pathlib import Path

from app.db.session import SessionLocal
from app.services import company_lookup, company_search

OUT = Path(__file__).resolve().parent.parent / "benchmarks"
# (query, kind): well-known Lebanese companies of every sector, Arabic / French spellings, domains, a few Gulf ones
QUERIES = [
    ("Bank Audi", "bank"), ("Byblos Bank", "bank"), ("IBL Bank", "bank"), ("Creditbank", "bank"),
    ("LIA Insurance", "insurer"), ("بنك عودة", "bank/ar"),
    ("Medgulf", "insurer"), ("Bankers Assurance", "insurer"), ("AXA Middle East", "insurer"),
    ("Spinneys Lebanon", "retail"), ("Aishti", "retail"), ("Le Charcutier Aoun", "retail"), ("ABC Verdun", "retail"),
    ("Chateau Ksara", "manufacturer"), ("Almaza Brewery", "manufacturer"), ("Gandour", "manufacturer"),
    ("Libanlait", "manufacturer"), ("Patchi", "manufacturer"), ("Indevco", "manufacturer"),
    ("International College", "school"), ("Collège Notre-Dame de Jamhour", "school/fr"),
    ("American Community School", "school"), ("Université Saint-Joseph", "university/fr"),
    ("Hôtel-Dieu de France", "hospital/fr"), ("Clemenceau Medical Center", "hospital"),
    ("Bellevue Medical Center", "hospital"), ("مستشفى الجامعة الأميركية في بيروت", "hospital/ar"),
    ("Cortas", "manufacturer"), ("Ogero", "telecom"), ("Massaya", "manufacturer"),
    ("Malak al Tawook", "restaurant"), ("شركة طيران الشرق الأوسط", "airline/ar"),
    ("Anghami", "tech"), ("Murex", "tech"), ("Born Interactive", "tech"), ("Middle East Airlines", "airline"), ("Mount Lebanon Hospital", "hospital"),
    ("Debbas", "contractor"), ("Malia Group", "group"),
    ("touch.com.lb", "domain"), ("anghami.com", "domain"), ("ksara.com.lb", "domain"),
    ("Emaar Properties in Dubai", "uae"), ("Aramex in Dubai", "uae"), ("Almarai in Saudi Arabia", "ksa"),
    ("Jarir Bookstore in Saudi Arabia", "ksa"),
]


def check() -> None:
    with SessionLocal() as db:
        for query, kind in QUERIES:
            hits = company_search.search(db, query)
            outcome, chosen = company_search.resolve(hits)
            print(f"{outcome:10} {query!r:45} {kind:20} " + "; ".join(
                f"{h.company.name} [{h.match_type}/{h.confidence}]" for h in hits[:3]))


def run(label: str) -> None:
    company_lookup.warm()
    company_lookup._extract_index(company_lookup.find_country("Lebanon"))  # built once, not timed
    rows = []
    with SessionLocal() as db:
        for query, kind in QUERIES:
            t = time.perf_counter()
            r = company_search.lookup(db, query, user_id=None)
            ms = int((time.perf_counter() - t) * 1000)
            rows.append({"query": query, "kind": kind, "status": r["status"], "ms": ms,
                         "company": (r["company"] or {}).get("name"), "match": r["match_type"],
                         "resolved_from": r["resolved_from"], "failure": r["failure_reason"],
                         "candidates": [(c["name"], c.get("source") or c.get("match_type"))
                                        for c in r["candidates"]][:5],
                         "sources": r["sources"]})
            print(f"{r['status']:10} {ms:6}ms {query!r:40} -> {rows[-1]['company'] or rows[-1]['candidates'][:2]} "
                  f"{r['resolved_from'] or r['failure_reason'] or ''} "
                  + ",".join(f"{s['source']}:{s['status']}:{s.get('found', s.get('error', ''))}"
                             for s in r["sources"]), flush=True)
    counts = {s: sum(r["status"] == s for r in rows) for s in ("found", "created", "ambiguous", "not_found",
                                                                 "timed_out")}
    summary = {"label": label, "n": len(rows), **counts,
               "median_ms": statistics.median(r["ms"] for r in rows)}
    print(summary)
    OUT.mkdir(exist_ok=True)
    (OUT / f"lookup_misses_{label}.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1,
                                                                 ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    {"check": lambda: check(), "run": lambda: run(sys.argv[2])}[sys.argv[1]]()
