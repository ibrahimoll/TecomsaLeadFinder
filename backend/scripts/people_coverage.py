"""People-coverage benchmark (development KPI, Step 5.1).

    python -m scripts.people_coverage select            # fix the 100 benchmark companies once (repeatable)
    python -m scripts.people_coverage measure before    # metrics for that fixed set -> benchmarks/people_coverage_before.json

The set is chosen by sector quotas, and within a sector in a pseudo-random but fixed order (md5 of the id): not
by how good a company's website is. Companies without a website are included.

USEFUL PEOPLE COVERAGE: share of companies with at least one credible (confidence >= 50) current or
not-confirmed business professional. DECISION-MAKER COVERAGE: share with such a person in one of the priority
departments (executive, IT, marketing, finance, sales, operations, procurement, HR). "current" variants count only
roles a recent source states as current.

SOURCE CONTRIBUTION (after entity resolution: one person = one, whatever the number of sources stating it):
unique credible people per source, companies with such a person per source, and the companies a source covers that
the company's own website did not (the website was the only source before Step 5.1).
"""

import json
import statistics
import sys
from collections import Counter
from pathlib import Path

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import Company, CompanyPerson, Evidence, Source

BENCHMARKS = Path(__file__).resolve().parent.parent / "benchmarks"
SET_FILE = BENCHMARKS / "people_coverage_set.json"
QUOTAS = {"Education": 10, "Hospitality": 10, "Retail": 10, "Manufacturing": 8, "Food Manufacturing": 4,
          "Food & Beverage": 6, "Construction": 5, "Real Estate": 5, "Financial Services": 7, "Insurance": 6,
          "Pharmaceutical": 5, "Healthcare": 6, "Technology": 6, "Distribution": 4, "Professional Services": 4,
          "Logistics": 2, "Automotive": 1, "Telecom": 1}
SIZE = 100
DECISION_DEPARTMENTS = ("executive", "it", "marketing", "finance", "sales", "operations", "procurement", "hr")
REPORT_DEPARTMENTS = ("executive", "it", "marketing", "finance", "sales", "hr", "operations", "procurement",
                      "supply_chain", "customer_experience", "manufacturing")
CREDIBLE = 50


def select_set() -> list[dict]:
    with SessionLocal() as db:
        order = func.md5(func.cast(Company.id, Company.name.type))
        chosen: list[Company] = []
        for industry, quota in QUOTAS.items():
            chosen += db.scalars(select(Company).where(Company.industry == industry).order_by(order).limit(quota)).all()
        if len(chosen) < SIZE:  # sectors with fewer companies: filled from the rest, same fixed order
            ids = [c.id for c in chosen]
            chosen += db.scalars(select(Company).where(Company.id.not_in(ids)).order_by(order)
                                 .limit(SIZE - len(chosen))).all()
        rows = [{"id": c.id, "name": c.name, "industry": c.industry, "website": c.website} for c in chosen[:SIZE]]
    BENCHMARKS.mkdir(exist_ok=True)
    SET_FILE.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return rows


HARD_SET_FILE = BENCHMARKS / "hard_sector_set.json"
# Step 5.3 hard-sector benchmark: the sectors Step 5.2 barely improved (deterministic, never by known people)
HARD_QUOTAS = {("Manufacturing", "Food Manufacturing"): 10, ("Retail",): 8, ("Hospitality",): 8, ("Technology",): 8,
               ("Distribution", "Logistics"): 6, ("Construction", "Real Estate"): 5, ("Professional Services",): 5}


def select_hard_set() -> list[dict]:
    with SessionLocal() as db:
        order = func.md5(func.concat(func.cast(Company.id, Company.name.type), "hard-sector"))
        chosen: list[Company] = []
        for industries, quota in HARD_QUOTAS.items():
            chosen += db.scalars(select(Company).where(Company.industry.in_(industries)).order_by(order)
                                 .limit(quota)).all()
        rows = [{"id": c.id, "name": c.name, "industry": c.industry, "website": c.website} for c in chosen]
    HARD_SET_FILE.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return rows


def measure(company_ids: list[int]) -> dict:
    """Coverage of these companies, from the canonical people database (whatever the source)."""
    with SessionLocal() as db:
        roles = db.execute(select(CompanyPerson.company_id, CompanyPerson.person_id, CompanyPerson.department,
                                  CompanyPerson.employment_status, CompanyPerson.confidence, CompanyPerson.id)
                           .where(CompanyPerson.company_id.in_(company_ids),
                                  CompanyPerson.confidence_components.is_not(None))).all()
        connectors: dict[int, set[str]] = {}  # role -> the sources stating it
        for role_id, connector, source_type in db.execute(
                select(Evidence.company_person_id, Source.metadata_["connector"].astext, Source.source_type)
                .join(Source, Source.id == Evidence.source_id)
                .where(Evidence.company_id.in_(company_ids), Evidence.company_person_id.is_not(None))):
            connectors.setdefault(role_id, set()).add(connector or (
                "company_website" if source_type == "company_website" else f"other:{source_type}"))
    origin = {role_id: bool(keys - {"company_website"}) for role_id, keys in connectors.items()}
    credible = [r for r in roles if r.employment_status != "former" and (r.confidence or 0) >= CREDIBLE]
    people: dict[int, set] = {cid: set() for cid in company_ids}
    departments: dict[int, set] = {cid: set() for cid in company_ids}
    for r in credible:
        people[r.company_id].add(r.person_id)
        departments[r.company_id].add(r.department)
    n = len(company_ids)
    counts = [len(people[c]) for c in company_ids]

    def share(k: int) -> float:
        return round(100 * k / n, 1) if n else 0.0

    with_person = sum(c >= 1 for c in counts)
    decision = sum(bool(departments[c] & set(DECISION_DEPARTMENTS)) for c in company_ids)
    current = [r for r in credible if r.employment_status == "current"]
    current_companies = {r.company_id for r in current}
    current_decision = {r.company_id for r in current if r.department in DECISION_DEPARTMENTS}
    by_source_people: dict[str, set] = {}
    by_source_companies: dict[str, set] = {}
    website_companies = set()
    for r in credible:
        for key in connectors.get(r.id, {"company_website"}):
            by_source_people.setdefault(key, set()).add(r.person_id)
            by_source_companies.setdefault(key, set()).add(r.company_id)
            if key == "company_website":
                website_companies.add(r.company_id)
    return {
        "companies": n,
        "with_1_person": with_person, "with_2_people": sum(c >= 2 for c in counts),
        "with_decision_maker": decision,
        "useful_people_coverage_pct": share(with_person), "decision_maker_coverage_pct": share(decision),
        "department_coverage": {d: sum(d in departments[c] for c in company_ids) for d in REPORT_DEPARTMENTS},
        "people_total": sum(counts),
        "people_avg": round(statistics.mean(counts), 2) if counts else 0,
        "people_median": statistics.median(counts) if counts else 0,
        "roles_from_external_sources": sum(bool(origin.get(r.id)) for r in credible),
        "roles_from_website_only": sum(not origin.get(r.id) for r in credible),
        "companies_by_people": dict(sorted(Counter(counts).items())),
        "companies_with_zero_people": sum(c == 0 for c in counts),
        "with_1_current_person": len(current_companies),
        "with_current_decision_maker": len(current_decision),
        "credible_roles_current": len(current), "credible_roles_not_confirmed": len(credible) - len(current),
        "by_source": {key: {"unique_people": len(by_source_people[key]),
                            "companies": len(by_source_companies[key]),
                            "companies_not_covered_by_website": len(by_source_companies[key] - website_companies)}
                      for key in sorted(by_source_people)},
        "people_per_company": {str(c): len(people[c]) for c in company_ids},
    }


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "measure"
    if command == "select-hard":
        rows = select_hard_set()
        print(f"{len(rows)} companies -> {HARD_SET_FILE}")
        print(dict(Counter(r["industry"] for r in rows)))
    elif command == "select":
        rows = select_set()
        print(f"{len(rows)} companies -> {SET_FILE}")
        print(dict(Counter(r["industry"] for r in rows)))
    else:
        label = sys.argv[2] if len(sys.argv) > 2 else "latest"
        set_file = HARD_SET_FILE if "--hard" in sys.argv else SET_FILE
        ids = [r["id"] for r in json.loads(set_file.read_text(encoding="utf-8"))]
        result = measure(ids)
        (BENCHMARKS / f"people_coverage_{label}.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
        print(json.dumps(result, indent=1))
