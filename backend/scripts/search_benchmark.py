"""Direct company search benchmark (Step 5.4).

    python -m scripts.search_benchmark select        # freeze the 100 queries + 20 unknown companies (once)
    python -m scripts.search_benchmark run LABEL     # run them -> benchmarks/direct_search_LABEL.json
    python -m scripts.search_benchmark run LABEL --unknown

Run against a disposable copy of the benchmark database (a lookup creates companies). Queries are chosen in a fixed
pseudo-random order (md5 of the id / name), never by how easy a company is:

    20 exact canonical names     10 legal-name variants (legal name / suffix added or removed)
    10 domains / website URLs    10 Arabic names (the company's Arabic name or alias)
    10 French / English aliases  10 brands (the name without its generic / sector / legal words)
    10 typos / transliterations   5 groups / subsidiaries (parent and child both known)
     5 global brand / local       5 ambiguous (a distinctive word several companies share)
     5 companies not in LeadFinder (organisations of the public-source corpus)

A result is CORRECT when the expected company is opened (found / created; for an absent company: a company with its
name), or for an ambiguous query when nothing is opened automatically. WRONG AUTOMATIC RESOLUTION: another company
opened. Top-1: the expected company is the first result (opened or first candidate).
"""

import hashlib
import json
import re
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import Company, CompanyAlias, ResearchRun

BENCHMARKS = Path(__file__).resolve().parent.parent / "benchmarks"
SET_FILE = BENCHMARKS / "direct_search_set.json"
UNKNOWN_FILE = BENCHMARKS / "direct_search_unknown_set.json"
CORPUS_SOURCES = ("ali_members", "idal_directories", "lcs_contractors", "berytech_profiles", "ministry_industry",
                  "odoo_customers", "project_lebanon", "icc_register", "gleif", "hospital_syndicate")
_ARABIC = re.compile(r"[؀-ۿ]")
_LEGAL_SUFFIX = re.compile(r"\s*[,(]?\s*\b(s\.?a\.?l|s\.?a\.?r\.?l|sal|sarl|ltd|llc|co\.?|inc)\b\.?\)?\s*$", re.I)
GROUPS = [("Fransabank Group", "Fransabank Group"), ("Fransabank", "Fransabank"), ("BLC Bank", "BLC bank"),
          ("Arope Insurance", "Arope Insurance"), ("BLOM Bank", "BLOM Bank")]
GLOBAL = [("Nike Lebanon", "Nike"), ("Radisson Blu Martinez Beirut", "Radisson Blu Martinez"),
          ("Movenpick Hotel Beirut", "Movenpick Beirut"), ("Chanel Beirut", "Chanel"),
          ("Nespresso Lebanon", "Nespresso")]


def _md5(value) -> str:
    return hashlib.md5(f"{value}|direct-search".encode()).hexdigest()


def _typo(name: str) -> str | None:
    """A realistic one-letter slip: y <-> i, a dropped vowel, a doubled consonant."""
    words = name.split()
    longest = max(range(len(words)), key=lambda i: len(words[i]))
    w = words[longest]
    if len(w) < 5:
        return None
    if "y" in w[1:]:
        w = w[0] + w[1:].replace("y", "i", 1)
    elif "i" in w[1:]:
        w = w[0] + w[1:].replace("i", "y", 1)
    else:
        vowels = [i for i, ch in enumerate(w) if ch.lower() in "aeou" and 0 < i < len(w) - 1]
        if vowels:
            w = w[:vowels[0]] + w[vowels[0] + 1:]
        else:
            w = w[:2] + w[1] + w[2:]
    words[longest] = w
    return " ".join(words)


_FR_EN = {"banque": "Bank", "bank": "Banque", "assurance": "Insurance", "assurances": "Insurance",
          "insurance": "Assurances", "libanaise": "Lebanese", "libanais": "Lebanese", "lebanese": "Libanaise",
          "compagnie": "Company", "company": "Compagnie", "generale": "General", "general": "Generale",
          "hotel": "Hôtel", "hôtel": "Hotel", "ecole": "School", "école": "School", "school": "Ecole",
          "laboratoire": "Laboratory", "laboratoires": "Laboratories", "pharmacie": "Pharmacy",
          "pharmacy": "Pharmacie", "hopital": "Hospital", "hôpital": "Hospital", "hospital": "Hôpital"}


def _translated(name: str | None) -> str | None:
    """The French / English form of a name ('Banque Misr Liban' -> 'Misr Liban Bank'), or None."""
    if not name:
        return None
    words = name.split()
    swapped = [_FR_EN.get(w.lower().strip(",."), w) for w in words]
    if swapped == words:
        return None
    if words[0].lower() in ("banque", "bank", "compagnie", "ecole", "école", "laboratoire", "pharmacie",
                            "hopital", "hôpital"):  # French noun first, English noun last
        swapped = swapped[1:] + swapped[:1]
    return " ".join(swapped)


def select_sets() -> tuple[list[dict], list[dict]]:
    from app.services.company_search import _core, name_keys
    from app.services.people.external.lebanon import pack
    from app.services.people.external.lebanon.identity import _GENERIC_WORDS
    from app.services.people.external.lebanon.records import _LEGAL, _SECTOR, PLACES, name_variants, org_key

    with SessionLocal() as db:
        companies = sorted(db.scalars(select(Company)).all(), key=lambda c: _md5(c.id))
        used: set[int] = set()
        out: list[dict] = []

        def take(kind: str, n: int, make) -> None:
            got = 0
            for c in companies:
                if got >= n or c.id in used:
                    continue
                query = make(c)
                if query:
                    out.append({"kind": kind, "query": query, "expected_id": c.id, "expected": c.name})
                    used.add(c.id)
                    got += 1

        full_keys = {k for c in companies for k in name_keys(c.name, c.legal_name) if k[0] not in "~^"}
        latin = lambda c: next((v for v in name_variants(c.name) if not _ARABIC.search(v)), None)  # noqa: E731
        take("exact", 20, lambda c: c.name if not _ARABIC.search(c.name) else None)
        take("legal", 10, lambda c: (c.legal_name if c.legal_name and org_key(c.legal_name) != org_key(c.name)
                                     and not _ARABIC.search(c.legal_name) else
                                     _LEGAL_SUFFIX.sub("", c.name) if _LEGAL_SUFFIX.search(c.name) else
                                     f"{latin(c)} S.A.L." if latin(c) else None))
        take("domain", 5, lambda c: c.domain)
        take("url", 5, lambda c: f"https://www.{c.domain}/en/contact-us" if c.domain else None)
        aliases = {}
        for a in db.scalars(select(CompanyAlias).order_by(CompanyAlias.id)):
            aliases.setdefault(a.company_id, []).append(a.alias)
        take("arabic", 10, lambda c: next((v for v in [*name_variants(c.name), *aliases.get(c.id, [])]
                                           if _ARABIC.search(v) and not re.search(r"[A-Za-z]", v)), None))
        take("alias", 10, lambda c: next((a for a in aliases.get(c.id, []) if not _ARABIC.search(a)
                                          and org_key(a) != org_key(c.name)), None))
        take("alias", 10 - sum(r["kind"] == "alias" for r in out), lambda c: _translated(latin(c)))

        def brand(c):
            name = latin(c)
            if not name or not _core(org_key(name)):
                return None
            words = [w for w in re.findall(r"[\w'&-]+", name) if org_key(w) and org_key(w) not in _SECTOR
                     and org_key(w) not in PLACES and org_key(w) not in _GENERIC_WORDS and org_key(w) not in _LEGAL]
            query = " ".join(words)
            if not words or query.lower() == name.lower() or org_key(query) in full_keys:
                return None  # a company is named exactly that: not a brand query
            return query
        take("brand", 10, brand)
        take("typo", 10, lambda c: _typo(latin(c)) if latin(c) else None)
        by_name = {c.name: c for c in companies}
        for kind, pairs in (("group", GROUPS), ("global_brand", GLOBAL)):
            for query, name in pairs:
                if name in by_name:
                    out.append({"kind": kind, "query": query, "expected_id": by_name[name].id, "expected": name})
        words = Counter()
        for c in companies:
            for w in {w for k in name_keys(c.name) if k[0] not in "~^" for w in k.split()}:
                if len(w) >= 4 and w not in _GENERIC_WORDS and w not in _SECTOR and w not in _LEGAL and \
                        not _ARABIC.search(w):
                    words[w] += 1
        shared = sorted((w for w, n in words.items() if n >= 2 and w not in full_keys), key=_md5)[:5]
        out += [{"kind": "ambiguous", "query": w.title(), "expected_id": None, "expected": "ambiguous"}
                for w in shared]
        keys = set().union(*(set(c.search_keys or []) for c in companies))
        absent: list[dict] = []
        seen: set[str] = set()
        per_source = {}
        for key in CORPUS_SOURCES:
            if key not in pack.configs():
                continue
            rows = []
            for row, records in pack._loaded(db, key):
                for r in records:
                    name = next((n for n in r.org if not _ARABIC.search(n)), None)
                    if r.person or not name or len(name.split()) < 2 or len(name) > 60:
                        continue
                    k = name_keys(name)
                    if k & keys or org_key(name) in seen or not ({x for x in k if x[0] not in "~^"}):
                        continue
                    rows.append({"kind": "absent", "query": _LEGAL_SUFFIX.sub("", name).strip(), "expected_id": None,
                                 "expected": name, "source": key})
            per_source[key] = sorted(rows, key=lambda r: _md5(r["expected"]))
        while len(absent) < 25 and any(per_source.values()):  # round robin over the sources
            for key in list(per_source):
                if per_source[key]:
                    row = per_source[key].pop(0)
                    if org_key(row["expected"]) not in seen:
                        seen.add(org_key(row["expected"]))
                        absent.append(row)
        out += absent[:5]
        return out, absent[5:25]


def run(rows: list[dict], label: str) -> dict:
    from app.services import company_search
    from app.services.company_search import name_keys

    from app.services import company_lookup

    results = []
    with SessionLocal() as db:
        for row in rows:
            t = time.perf_counter()
            saved = company_lookup._corpus, company_lookup._extracts
            if row.get("web_only"):  # a company no source holds: only the web can find it
                company_lookup._corpus = lambda *a, **k: []
                company_lookup._extracts = lambda *a, **k: []
            try:
                r = company_search.lookup(db, row["query"], user_id=None, country="Lebanon")
            finally:
                company_lookup._corpus, company_lookup._extracts = saved
            seconds = round(time.perf_counter() - t, 3)
            company = r.get("company") or {}
            top = company or (r["candidates"][0] if r["candidates"] else {})
            opened = r["status"] in ("found", "created")
            if row.get("expected_domain"):  # web only: the company's own site, verified
                site = db.get(Company, company["company_id"]).website if company.get("company_id") else None
                from app.services.normalization import company_domain
                correct = opened and company_domain(site) == row["expected_domain"]
                top1, wrong = correct, opened and not correct
            elif row["expected_id"] is not None:
                correct = opened and company.get("company_id") == row["expected_id"]
                top1 = top.get("company_id") == row["expected_id"]
                wrong = opened and not correct
            elif row["kind"] == "nonexistent":  # an invented name: nothing may be opened or created
                correct, top1, wrong = not opened, not opened, opened
            elif row["kind"] == "ambiguous":
                correct, top1, wrong = not opened, not opened, opened
            else:  # absent: a company with the organisation's name (created, or reused if created earlier)
                correct = opened and bool(name_keys(company.get("name") or "") & name_keys(row["expected"]))
                top1, wrong = correct, opened and not correct
            created_id = company.get("company_id") if r.get("created") else None
            queued = bool(created_id and db.scalar(select(func.count()).select_from(ResearchRun).where(
                ResearchRun.company_id == created_id)))
            results.append({**row, "status": r["status"], "top": top.get("name"), "top_id": top.get("company_id"),
                            "match_type": r.get("match_type") or top.get("match_type"),
                            "confidence": r.get("confidence") or top.get("confidence"), "correct": correct,
                            "top1": top1, "wrong_auto": wrong, "db_hit": not r["external_used"],
                            "external_used": r["external_used"], "created": r.get("created", False),
                            "research_queued": queued, "candidates": len(r["candidates"]),
                            "sources": [f"{s['source']}:{s['status']}" for s in r.get("sources", [])],
                            "resolved_from": r.get("resolved_from"), "failure_reason": r.get("failure_reason"),
                            "parsed": r.get("parsed"), "seconds": seconds})
            print(f"{row['kind']:12} {row['query'][:34]:34} -> {r['status']:9} {str(top.get('name'))[:30]:30} "
                  f"{'OK ' if correct else 'WRONG' if wrong else '-- '} {seconds}s", flush=True)
        duplicates = db.execute(select(Company.normalized_name, func.count()).group_by(Company.normalized_name)
                                .having(func.count() > 1)).all()
    report = {"label": label, "queries": len(results), "kpis": kpis(results),
              "duplicate_normalized_names_after": [list(d) for d in duplicates], "results": results}
    return report


def kpis(results: list[dict]) -> dict:
    def pct(rows, key="correct"):
        return round(100 * sum(r[key] for r in rows) / len(rows), 1) if rows else None

    by = lambda *kinds: [r for r in results if r["kind"] in kinds]  # noqa: E731
    seconds = sorted(r["seconds"] for r in results)
    return {
        "top1_correct_pct": pct(results, "top1"), "auto_resolution_correct_pct": pct(results),
        "exact_domain_pct": pct(by("exact", "domain", "url")), "alias_pct": pct(by("alias", "legal", "brand")),
        "arabic_pct": pct(by("arabic")), "french_english_alias_pct": pct(by("alias")), "typo_pct": pct(by("typo")),
        "group_pct": pct(by("group")), "global_brand_pct": pct(by("global_brand")),
        "ambiguous_left_ambiguous_pct": pct(by("ambiguous")), "absent_found_pct": pct(by("absent")),
        "wrong_auto_resolutions": sum(r["wrong_auto"] for r in results),
        "not_found_pct": round(100 * sum(r["status"] == "not_found" for r in results) / len(results), 1),
        "db_hit_pct": pct(results, "db_hit"), "external_lookup_pct": pct(results, "external_used"),
        "new_company_pct": pct(results, "created"),
        "median_seconds": round(statistics.median(seconds), 3),
        "p90_seconds": round(seconds[int(0.9 * (len(seconds) - 1))], 3),
        "p99_seconds": round(seconds[int(0.99 * (len(seconds) - 1))], 3),
        "found_pct": pct([{**r, "f": r["status"] in ("found", "created")} for r in results], "f"),
        "ambiguous_pct": round(100 * sum(r["status"] == "ambiguous" for r in results) / len(results), 1),
        "resolved_from": dict(Counter((r.get("resolved_from") or "-").split(":")[0] for r in results
                                      if r["status"] in ("found", "created"))),
        "failure_reasons": dict(Counter(r.get("failure_reason") for r in results if r.get("failure_reason"))),
        "by_kind": {k: {"n": len(by(k)), "correct": sum(r["correct"] for r in by(k)),
                        "top1": sum(r["top1"] for r in by(k)), "wrong": sum(r["wrong_auto"] for r in by(k))}
                    for k in dict.fromkeys(r["kind"] for r in results)},
    }


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "run"
    if command == "select":
        main, unknown = select_sets()
        SET_FILE.write_text(json.dumps(main, ensure_ascii=False, indent=1), encoding="utf-8")
        UNKNOWN_FILE.write_text(json.dumps(unknown, ensure_ascii=False, indent=1), encoding="utf-8")
        print(len(main), dict(Counter(r["kind"] for r in main)), "unknown:", len(unknown))
    else:
        label = sys.argv[2] if len(sys.argv) > 2 else "latest"
        unknown = "--unknown" in sys.argv
        rows = json.loads((UNKNOWN_FILE if unknown else SET_FILE).read_text(encoding="utf-8"))
        report = run(rows, label)
        name = f"direct_search_{'unknown_' if unknown else ''}{label}.json"
        (BENCHMARKS / name).write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(json.dumps(report["kpis"], indent=1))
