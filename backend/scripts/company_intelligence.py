"""Company-intelligence KPIs (development benchmark), on the same fixed companies as the people benchmark.

    python -m scripts.company_intelligence measure LABEL        -> benchmarks/company_intelligence_LABEL.json
    python -m scripts.company_intelligence sources              per-source contribution (whole database)
    python -m scripts.company_intelligence sales IDS            the sales-quality table for these companies

Every figure is a share of companies WITH the field (with evidence), never a score.
"""

import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import func, literal_column, select

from app.db.session import SessionLocal
from app.models import (Company, CompanyLocation, CompanyOffering, CompanyPerson, CompanyRelationship, CompanySignal,
                        Evidence, ExternalDocument, Source)
from app.models.enums import SIGNAL_GROUPS

BENCHMARKS = Path(__file__).resolve().parent.parent / "benchmarks"
SITES = ("branch", "store", "factory", "warehouse", "showroom", "restaurant")
TECH = ("technology", "email_provider", "dns_provider", "email_sending_service")
EVENTS = ("procurement_award", "acquisition", "funding", "management_change", "factory_opening", "warehouse_opening",
          "branch_opening", "distribution_agreement", "partnership", "ecommerce_launch", "new_market", "new_product",
          "expansion", "hiring")
DECISION = ("executive", "it", "finance", "marketing", "sales", "hr", "operations", "procurement")


def _by_company(db, stmt) -> dict[int, set]:
    out: dict[int, set] = defaultdict(set)
    for company_id, value in db.execute(stmt):
        out[company_id].add(value)
    return out


def facts(db, ids: list[int]) -> dict[int, dict]:
    companies = {c.id: c for c in db.scalars(select(Company).where(Company.id.in_(ids)))}
    signals = _by_company(db, select(CompanySignal.company_id, CompanySignal.signal_type)
                          .where(CompanySignal.company_id.in_(ids)))
    events = _by_company(db, select(CompanySignal.company_id, CompanySignal.event_date).where(
        CompanySignal.company_id.in_(ids), CompanySignal.event_date.is_not(None),
        CompanySignal.signal_type != "domain_registered"))
    locations = _by_company(db, select(CompanyLocation.company_id, CompanyLocation.location_type)
                            .where(CompanyLocation.company_id.in_(ids)))
    offerings = _by_company(db, select(CompanyOffering.company_id, CompanyOffering.kind)
                            .where(CompanyOffering.company_id.in_(ids)))
    relations = _by_company(db, select(CompanyRelationship.company_id, CompanyRelationship.relation_type)
                            .where(CompanyRelationship.company_id.in_(ids)))
    size = _by_company(db, select(Evidence.company_id, Evidence.field_name).where(
        Evidence.company_id.in_(ids), Evidence.field_name.in_(("employee_count", "employee_count_estimate",
                                                               "employee_count_min", "employee_count_max"))))
    people = _by_company(db, select(CompanyPerson.company_id, CompanyPerson.department).where(
        CompanyPerson.company_id.in_(ids), CompanyPerson.employment_status != "former", CompanyPerson.confidence >= 50))
    people_n = dict(db.execute(select(CompanyPerson.company_id, func.count(func.distinct(CompanyPerson.person_id)))
                               .where(CompanyPerson.company_id.in_(ids), CompanyPerson.employment_status != "former",
                                      CompanyPerson.confidence >= 50).group_by(CompanyPerson.company_id)).all())
    sources = dict(db.execute(select(Evidence.company_id, func.count(func.distinct(Evidence.source_id)))
                              .where(Evidence.company_id.in_(ids)).group_by(Evidence.company_id)).all())
    recent = date.today() - timedelta(days=548)
    out = {}
    for cid in ids:
        c = companies.get(cid)
        if c is None:
            continue
        s, ev = signals[cid], events[cid]
        out[cid] = {
            "name": c.name, "industry": c.industry,
            "verified website": bool(c.domain and (c.website_confidence or 0) >= 60),
            "description": bool(c.description),
            "products / services": bool(offerings[cid]),
            "locations": bool(locations[cid]),
            "branch / store / factory / warehouse": bool(locations[cid] & set(SITES)) or bool(
                s & {"branches", "retail_stores", "factory", "warehouse", "showrooms", "distribution_center"}),
            "public phone": bool(c.primary_phone), "public company e-mail": bool(c.primary_email),
            "parent / subsidiary": bool(relations[cid]),
            "technology": bool(s & set(TECH)),
            "employee-size evidence": bool(size[cid]),
            "recent business signal": any(d >= recent for d in ev),
            "procurement signal": "procurement_award" in s,
            "timeline events": bool(ev),
            "operations": bool(s & (set(SIGNAL_GROUPS["activity"]) | set(SIGNAL_GROUPS["operations"]))),
            "_people": people_n.get(cid, 0), "_decision": sorted(people[cid] & set(DECISION)),
            "_locations": len(locations[cid]), "_sources": sources.get(cid, 0),
            "_signals": sorted(t for t in s if t in EVENTS), "_tech": sorted(t for t in s if t in TECH),
            "_completeness": c.completeness,
        }
    return out


def measure(ids: list[int]) -> dict:
    with SessionLocal() as db:
        rows = facts(db, ids)
    n = len(rows)
    keys = [k for k in next(iter(rows.values())) if not k.startswith("_") and k not in ("name", "industry")]
    return {"companies": n, **{k: round(100 * sum(r[k] for r in rows.values()) / n, 1) for k in keys}}


def contribution() -> dict:
    """Per source: documents, companies enriched, credible people, company facts, signals (whole database)."""
    one = literal_column("1")
    with SessionLocal() as db:
        key = func.coalesce(Source.metadata_["connector"].astext, Source.source_type)
        docs = dict(db.execute(select(ExternalDocument.metadata_["source"].astext, func.count()).group_by(one)).all())
        companies = dict(db.execute(select(key, func.count(func.distinct(Evidence.company_id))).select_from(Evidence)
                                    .join(Source, Source.id == Evidence.source_id).group_by(one)).all())
        people = dict(db.execute(select(key, func.count(func.distinct(CompanyPerson.person_id)))
                                 .select_from(CompanyPerson)
                                 .join(Evidence, Evidence.company_person_id == CompanyPerson.id)
                                 .join(Source, Source.id == Evidence.source_id)
                                 .where(CompanyPerson.confidence >= 50, CompanyPerson.employment_status != "former")
                                 .group_by(one)).all())
        company_facts = dict(db.execute(select(key, func.count()).select_from(Evidence)
                                        .join(Source, Source.id == Evidence.source_id)
                                        .where(Evidence.company_person_id.is_(None)).group_by(one)).all())
        signals = dict(db.execute(select(key, func.count()).select_from(CompanySignal)
                                  .join(Source, Source.id == CompanySignal.source_id).group_by(one)).all())
    names = sorted(set(docs) | set(companies) | set(people) | set(signals), key=str)
    return {str(n): {"documents": docs.get(n, 0), "companies_enriched": companies.get(n, 0),
                     "people": people.get(n, 0), "company_facts": company_facts.get(n, 0),
                     "signals": signals.get(n, 0)} for n in names if n}

if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "measure"
    if command == "measure":
        label = sys.argv[2] if len(sys.argv) > 2 else "latest"
        ids = [r["id"] for r in json.loads((BENCHMARKS / "people_coverage_set.json").read_text(encoding="utf-8"))]
        result = measure(ids)
        (BENCHMARKS / f"company_intelligence_{label}.json").write_text(json.dumps(result, indent=1),
                                                                     encoding="utf-8")
        print(json.dumps(result, indent=1))
    elif command == "sources":
        print(json.dumps(contribution(), indent=1))
    elif command == "sales":
        ids = [int(x) for x in sys.argv[2].split(",")]
        with SessionLocal() as db:
            rows = facts(db, ids)
        print(json.dumps(rows, indent=1, default=str, ensure_ascii=False))
