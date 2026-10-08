"""Contactability benchmark (Step 6): can LeadFinder name the person to contact and how to reach them?

    python -m scripts.contact_coverage measure LABEL           # the fixed 100 (people_coverage_set.json)
    python -m scripts.contact_coverage measure LABEL --sales   # the 50 sales-relevant companies (hard_sector_set)

RELEVANT DECISION-MAKER: a credible (confidence >= 50), current role in a department TECOMSA sells to, at manager
level or above. CONTACT CHANNELS of a person, strongest first: verified work email, published work email, published
business mobile, published direct business phone, published WhatsApp, office extension; a predicted email never
counts. DIRECTLY CONTACTABLE: a decision-maker with one of those. REACHABLE VIA SWITCHBOARD ONLY (reported apart,
never added to the direct rate): no direct channel, but a named decision-maker at a company with a published main line.
"""

import json
import sys
from collections import Counter
from pathlib import Path

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Company, CompanyPerson, Email, Phone

BENCHMARKS = Path(__file__).resolve().parent.parent / "benchmarks"
from app.services.contact_intelligence import DM_DEPARTMENTS, DM_SENIORITY  # noqa: E402
PUBLISHED = ("published", "discovered")
DIRECT = ("direct_business_phone", "office", "landline")
MOBILE = ("business_mobile", "mobile")


def person_channels(db, person_id: int, company_id: int) -> dict:
    emails = db.scalars(select(Email).where(Email.person_id == person_id)).all()
    phones = db.scalars(select(Phone).where(Phone.person_id == person_id)).all()
    return {
        "verified_email": any(e.status == "verified" for e in emails),
        "published_email": any(e.status in PUBLISHED and e.email_type == "work" for e in emails),
        "predicted_email": any(e.status == "predicted" for e in emails),
        "high_confidence_email": any(e.status == "high_confidence_predicted" for e in emails),
        "confirmed_email": any(e.status == "confirmed" for e in emails),
        "catch_all_email": any(e.status == "catch_all" for e in emails),
        "mobile": any(p.phone_type in MOBILE for p in phones),
        "direct_phone": any(p.phone_type in DIRECT for p in phones),
        "whatsapp": any(p.phone_type == "whatsapp" for p in phones),
        "extension": any(p.phone_type == "office_extension" for p in phones),
        "unconfirmed_phone": any(p.phone_type == "unknown_business" for p in phones),
    }


def usable(ch: dict) -> bool:
    return any(ch[k] for k in ("confirmed_email", "verified_email", "published_email", "mobile", "direct_phone",
                               "whatsapp", "extension"))


def best_method(ch: dict) -> str | None:
    for key in ("verified_email", "published_email", "mobile", "direct_phone", "whatsapp", "extension",
                "predicted_email"):
        if ch[key]:
            return key
    return None


def measure(ids: list[int]) -> dict:
    out = Counter()
    rows = []
    with SessionLocal() as db:
        for cid in ids:
            company = db.get(Company, cid)
            roles = db.scalars(select(CompanyPerson).where(
                CompanyPerson.company_id == cid, CompanyPerson.confidence >= 50,
                CompanyPerson.employment_status == "current")).all()
            switchboard = bool(company.primary_phone or db.scalar(select(Phone.id).where(
                Phone.company_id == cid, Phone.person_id.is_(None)).limit(1)))
            people = {r.person_id: r for r in roles}
            dms = {pid: r for pid, r in people.items() if r.department in DM_DEPARTMENTS
                   and r.seniority in DM_SENIORITY}
            channels = {pid: person_channels(db, pid, cid) for pid in people}
            contactable = [pid for pid in dms if usable(channels[pid])]
            for pid, ch in channels.items():
                for key, value in ch.items():
                    out[f"people_with_{key}"] += value
                    out[f"decision_makers_with_{key}"] += value and pid in dms
            out["people_total"] += len(people)
            out["decision_makers_total"] += len(dms)
            out["companies_with_person"] += bool(people)
            out["companies_with_decision_maker"] += bool(dms)
            out["companies_with_2_decision_makers"] += len(dms) >= 2
            out["companies_contactable_strict"] += bool(contactable)
            out["companies_contactable_2_strict"] += len(contactable) >= 2
            # a named decision-maker + the company's main line: reachable, never counted as directly contactable
            out["companies_reachable_via_switchboard_only"] += bool(not contactable and dms and switchboard)
            best = max((best_method(channels[pid]) for pid in dms), key=lambda m: m is not None, default=None)
            rows.append({"id": cid, "company": company.name, "industry": company.industry, "people": len(people),
                         "decision_makers": len(dms), "contactable": len(contactable),
                         "best_department": next((dms[p].department for p in contactable or dms), None),
                         "best_method": best or ("company_switchboard" if dms and switchboard else None)})
    return {"companies": len(ids), **dict(out), "sources": contributions(ids), "rows": rows}


USABLE_EMAIL = ("published", "discovered", "verified", "confirmed")
USABLE_PHONE = DIRECT + MOBILE + ("whatsapp", "office_extension")


def contributions(ids: list[int]) -> dict:
    """Per source type: current relevant decision-makers it states, the companies they are at, the usable contacts it
    published and the companies it made directly contactable (a company counts for every source of a usable
    channel of one of its decision-makers)."""
    from app.models import Evidence, Source

    acc: dict[str, dict] = {}

    def slot(kind: str) -> dict:
        return acc.setdefault(kind, {"decision_makers": 0, "dm_companies": set(), "usable_contacts": 0,
                                     "contactable_companies": set()})
    with SessionLocal() as db:
        for cid in ids:
            roles = db.scalars(select(CompanyPerson).where(
                CompanyPerson.company_id == cid, CompanyPerson.confidence >= 50,
                CompanyPerson.employment_status == "current", CompanyPerson.department.in_(DM_DEPARTMENTS),
                CompanyPerson.seniority.in_(DM_SENIORITY))).all()
            for role in roles:
                for kind in set(db.scalars(select(Source.source_type).join(Evidence, Evidence.source_id == Source.id)
                                           .where(Evidence.company_person_id == role.id))):
                    slot(kind)["decision_makers"] += 1
                    slot(kind)["dm_companies"].add(cid)
                points = [(e.source_id, e.provenance) for e in db.scalars(select(Email).where(
                    Email.person_id == role.person_id, Email.status.in_(USABLE_EMAIL)))]
                points += [(p.source_id, p.provenance) for p in db.scalars(select(Phone).where(
                    Phone.person_id == role.person_id, Phone.phone_type.in_(USABLE_PHONE),
                    Phone.status != "invalid"))]
                for source_id, provenance in points:
                    kind = db.scalar(select(Source.source_type).where(Source.id == source_id)) if source_id                         else f"({provenance})"
                    slot(kind)["usable_contacts"] += 1
                    slot(kind)["contactable_companies"].add(cid)
    return {k: {**v, "dm_companies": len(v["dm_companies"]), "contactable_companies": len(v["contactable_companies"])}
            for k, v in sorted(acc.items())}


if __name__ == "__main__":
    label = sys.argv[2] if len(sys.argv) > 2 else "latest"
    sales = "--sales" in sys.argv
    source = BENCHMARKS / ("hard_sector_set.json" if sales else "people_coverage_set.json")
    data = json.loads(source.read_text(encoding="utf-8"))
    data = data if isinstance(data, list) else data.get("companies", data)
    ids = [r["id"] if isinstance(r, dict) else int(r) for r in data]
    result = measure(ids)
    (BENCHMARKS / f"contact_coverage_{'sales_' if sales else ''}{label}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=1))
