"""Field completeness of a company's intelligence: what LeadFinder knows, area by area, and what is still missing.

Percentages of FIELDS PRESENT (with evidence), never a confidence or a quality score. Stored on the company
(companies.completeness) after each research job; background research can use `missing` to target what to look for.

    identity     website confirmed, description, industry, legal identity (legal name / registry / LEI / licence),
                 founding year
    operations   what it does (activity) and how it operates (factories, warehouses, branches, delivery...)
    locations    any location; a typed site (headquarters, branch, factory, warehouse, store, showroom)
    people       priority departments with a credible person (executive, IT, finance, marketing, sales, HR,
                 operations, procurement)
    technology   website technology; e-mail / DNS provider
    contacts     public company phone; public company e-mail
    signals      a dated business event in the last 18 months
    size         employee-count evidence
"""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Company, CompanyIdentifier, CompanyLocation, CompanyPerson, CompanySignal, Evidence
from app.models.enums import SIGNAL_GROUPS

PRIORITY = ("executive", "it", "finance", "marketing", "sales", "hr", "operations", "procurement")
DEPARTMENT_LABEL = {"executive": "executive decision-maker", "it": "IT decision-maker",
                    "finance": "finance decision-maker", "marketing": "marketing decision-maker",
                    "sales": "sales decision-maker", "hr": "HR decision-maker",
                    "operations": "operations decision-maker", "procurement": "procurement decision-maker"}
_TYPED_SITES = ("headquarters", "branch", "factory", "warehouse", "store", "showroom", "office", "restaurant")
_IDENTITY_SCHEMES = ("registry:LB", "lei", "icc_licence", "bdl_bank_list", "moi_factory")


def compute(db: Session, company: Company) -> dict:
    signals = {t for (t,) in db.execute(select(CompanySignal.signal_type).where(
        CompanySignal.company_id == company.id).distinct())}
    recent_event = db.scalar(select(func.count()).select_from(CompanySignal).where(
        CompanySignal.company_id == company.id, CompanySignal.event_date >= date.today() - timedelta(days=548),
        CompanySignal.signal_type != "domain_registered"))
    location_types = {t for (t,) in db.execute(select(CompanyLocation.location_type).where(
        CompanyLocation.company_id == company.id))}
    identifiers = {s for (s,) in db.execute(select(CompanyIdentifier.scheme).where(
        CompanyIdentifier.company_id == company.id))}
    departments = {d for (d,) in db.execute(select(CompanyPerson.department).where(
        CompanyPerson.company_id == company.id, CompanyPerson.employment_status != "former",
        CompanyPerson.confidence >= 50))}
    size_evidence = db.scalar(select(func.count()).select_from(Evidence).where(
        Evidence.company_id == company.id, Evidence.field_name.in_(("employee_count", "employee_count_estimate",
                                                                    "employee_count_min", "employee_count_max"))))
    fields = {
        "identity": {"website confirmed": bool(company.domain and (company.website_confidence or 0) >= 60),
                     "description": bool(company.description), "industry": bool(company.industry),
                     "legal identity": bool(company.legal_name or identifiers & set(_IDENTITY_SCHEMES)),
                     "founding year": bool(company.founded_year)},
        "operations": {"activity": bool(signals & set(SIGNAL_GROUPS["activity"])),
                       "operating model": bool(signals & set(SIGNAL_GROUPS["operations"]))},
        "locations": {"location": bool(location_types), "typed site": bool(location_types & set(_TYPED_SITES))},
        "people": {DEPARTMENT_LABEL[d]: d in departments for d in PRIORITY},
        "technology": {"website technology": "technology" in signals,
                       "e-mail / DNS provider": bool(signals & {"email_provider", "dns_provider"})},
        "contacts": {"company phone": bool(company.primary_phone), "company e-mail": bool(company.primary_email)},
        "signals": {"recent business event": bool(recent_event)},
        "size": {"employee count": bool(size_evidence or company.employee_count_estimate)},
    }
    out: dict = {area: round(100 * sum(v.values()) / len(v)) for area, v in fields.items()}
    out["missing"] = [name for area in fields.values() for name, present in area.items() if not present]
    out["computed_at"] = datetime.now(timezone.utc).isoformat()
    return out


def update(db: Session, company: Company) -> dict:
    company.completeness = compute(db, company)
    return company.completeness
