"""Evidence-first persistence of website facts.

Every Fact becomes an Evidence row (source page + excerpt + confidence + date) before anything else changes:

    "ABC operates three factories"  ->  evidence(company, factory_count, "3", source = abc.com/about, excerpt)
                                    ->  company_signals(factory, "3")

Canonical company fields are then (re)chosen from all the evidence of that field, whatever its source:
highest confidence first, most recent on a tie. Conflicting values all stay as evidence (conflicts() lists
them); a value a person typed in (one no evidence supports) is never overwritten. Contacts, locations,
signals and products are upserted, never duplicated; re-reading an unchanged page adds nothing.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import (Company, CompanyLocation, CompanyOffering, CompanySignal, Email, Evidence, Phone,
                        Source)
from app.services.discovery.consolidation import name_tokens
from app.services.discovery.persistence import _km
from app.services.enrichment.extract import Fact, normalize_offering

WEBSITE_QUALITY = 80  # the company's own website, once confirmed as its own
PAGE_LABELS = {"homepage": "Home page", "about": "About page", "contact": "Contact page", "locations": "Locations page",
               "products": "Products page", "services": "Services page", "manufacturing": "Manufacturing page",
               "careers": "Careers page", "news": "News page", "team": "Team page", "other": "Page"}
# Company column <- the evidence fields that support it (Step 3 sources included, e.g. Wikidata employee_count).
CANONICAL = {
    "description": ("description",),
    "legal_name": ("legal_name",),
    "founded_year": ("founded_year",),
    "employee_count_estimate": ("employee_count_estimate", "employee_count"),
    "employee_count_min": ("employee_count_min",),
    "employee_count_max": ("employee_count_max",),
}
_INT_COLUMNS = {"founded_year", "employee_count_estimate", "employee_count_min", "employee_count_max"}
CONFLICT_FIELDS = ("legal_name", "founded_year", "employee_count_estimate", "employee_count_min",
                   "employee_count_max")
SOCIAL_COLUMNS = {"facebook": "facebook_url", "instagram": "instagram_url", "linkedin": "linkedin_url",
                  "youtube": "youtube_url", "tiktok": "tiktok_url", "twitter": "twitter_url"}
_EVIDENCE_TYPE = {"field": "company_fact", "phone": "contact_point", "email": "contact_point", "social": "company_fact",
                  "location": "location", "offering": "company_fact", "signal": "signal"}


def page_source(db: Session, company: Company, *, url: str, digest: str, page_type: str, title: str | None,
                retrieved_at: datetime, quality: int) -> Source:
    """One source per page version: the same URL with the same content is the same source."""
    existing = db.scalar(select(Source).where(Source.content_hash == digest, Source.url == url).limit(1))
    if existing:
        return existing
    source = Source(source_type="company_website", name=f"Official website · {PAGE_LABELS.get(page_type, 'Page')}",
                    url=url[:2000], publisher=company.name[:300], retrieved_at=retrieved_at, source_quality=quality,
                    content_hash=digest, metadata_={"page_type": page_type, "title": title})
    db.add(source)
    db.flush()
    return source


def _field(fact: Fact) -> str:
    if fact.kind == "social":
        return SOCIAL_COLUMNS[fact.name]
    if fact.kind == "signal":
        return fact.extra.get("count_field") or fact.name
    return fact.name


def _value(fact: Fact) -> str:
    if fact.kind == "location":
        return fact.value["address"]
    return str(fact.value if fact.value is not None else fact.name)[:2000]


def evidence(db: Session, source: Source, company: Company, fact: Fact, observed_at: datetime) -> Evidence:
    field, value = _field(fact), _value(fact)
    existing = db.scalar(select(Evidence).where(Evidence.source_id == source.id, Evidence.company_id == company.id,
                                                Evidence.field_name == field, Evidence.extracted_value == value)
                         .limit(1))
    if existing:
        return existing
    row = Evidence(source_id=source.id, company_id=company.id, evidence_type=_EVIDENCE_TYPE[fact.kind],
                   field_name=field, extracted_value=value, excerpt=fact.excerpt,
                   structured_value=fact.value if fact.kind == "location" else (fact.extra or None),
                   confidence=max(0, min(100, fact.confidence)), observed_at=observed_at)
    db.add(row)
    db.flush()
    return row


def _phone(db: Session, company: Company, fact: Fact, source: Source, now: datetime) -> None:
    row = db.scalar(select(Phone).where(Phone.company_id == company.id, Phone.person_id.is_(None),
                                        Phone.normalized_phone == fact.value))
    if row is None:
        row = Phone(company_id=company.id, phone=fact.extra["published"] or fact.value, normalized_phone=fact.value,
                    phone_type=fact.extra["phone_type"], purpose=fact.extra["purpose"], is_public=True,
                    confidence=fact.confidence, source_id=source.id, first_seen_at=now)
        db.add(row)
        db.flush()  # the same number can appear twice on one page (a tel: link and the text)
    else:
        row.confidence = max(row.confidence or 0, fact.confidence)
        row.purpose = row.purpose if row.purpose not in (None, "general") else fact.extra["purpose"]
        if row.phone_type in (None, "unknown"):
            row.phone_type = fact.extra["phone_type"]
    row.last_seen_at = now
    if not company.primary_phone and fact.extra["phone_type"] != "whatsapp":
        company.primary_phone = row.phone


def _email(db: Session, company: Company, fact: Fact, source: Source, now: datetime) -> None:
    row = db.scalar(select(Email).where(Email.company_id == company.id, Email.person_id.is_(None),
                                        Email.email == fact.value))
    if row is None:
        row = Email(company_id=company.id, email=fact.value, email_type="generic", purpose=fact.extra["purpose"],
                    is_public=True, confidence=fact.confidence, source_id=source.id, first_seen_at=now,
                    status="published")
        db.add(row)
        db.flush()  # the same address can appear twice on one page (a mailto: link and the text)
    else:
        row.confidence = max(row.confidence or 0, fact.confidence)
        row.purpose = row.purpose or fact.extra["purpose"]
    row.last_seen_at = now
    if not company.primary_email:
        company.primary_email = fact.value


_COUNTRY_WORDS = {"lebanon", "liban", "lb", "لبنان"}


def _address_key(text: str | None) -> set[str]:
    return set(name_tokens(text or "")) - _COUNTRY_WORDS


def same_place(loc: CompanyLocation, new: dict[str, Any]) -> bool:
    """Only clear matches merge (coordinates within 500 m, the same address, phone or name in the same city);
    anything uncertain stays a separate row rather than being merged wrongly."""
    if None not in (loc.latitude, loc.longitude, new.get("latitude"), new.get("longitude")):
        return _km((loc.latitude, loc.longitude), (new["latitude"], new["longitude"])) <= 0.5
    a, b = _address_key(loc.address), _address_key(new.get("address"))
    if a and b and len(a & b) / len(a | b) >= 0.8:
        return True
    if loc.phone and loc.phone == new.get("phone"):
        return True
    same_city = (loc.city or "").lower() == (new.get("city") or "").lower()
    return bool(same_city and loc.name and new.get("name") and loc.name.lower() == new["name"].lower())


def _location(db: Session, company: Company, fact: Fact, source: Source, country: str) -> None:
    new = fact.value
    locations = db.scalars(select(CompanyLocation).where(CompanyLocation.company_id == company.id)).all()
    match = next((loc for loc in locations if same_place(loc, new)), None)
    if match:  # complete what was missing, never overwrite
        for column in ("address", "name", "phone", "city", "region", "latitude", "longitude", "location_type"):
            if getattr(match, column) in (None, "") and new.get(column) not in (None, ""):
                setattr(match, column, new[column])
        match.confidence = max(match.confidence or 0, fact.confidence)
        return
    db.add(CompanyLocation(
        company_id=company.id, location_type=new.get("location_type"), country=country, region=new.get("region"),
        city=new.get("city"), address=new.get("address"), latitude=new.get("latitude"),
        longitude=new.get("longitude"), name=(new.get("name") or None) and new["name"][:200], phone=new.get("phone"),
        is_headquarters=new.get("location_type") == "headquarters" and not any(l.is_headquarters for l in locations),
        source_id=source.id, confidence=fact.confidence))
    db.flush()


def _signal(db: Session, company: Company, fact: Fact, source: Source, row: Evidence, now: datetime) -> None:
    stmt = insert(CompanySignal).values(company_id=company.id, signal_type=fact.name, signal_value=fact.value,
                                        confidence=fact.confidence, source_id=source.id, evidence_id=row.id,
                                        observed_at=now)
    db.execute(stmt.on_conflict_do_update(
        index_elements=["company_id", "signal_type", "signal_value"],
        set_={"confidence": func.greatest(CompanySignal.confidence, stmt.excluded.confidence),
              "source_id": stmt.excluded.source_id, "evidence_id": stmt.excluded.evidence_id,
              "observed_at": stmt.excluded.observed_at}))


def offering(db: Session, company: Company, fact: Fact, source: Source) -> None:
    stmt = insert(CompanyOffering).values(company_id=company.id, kind=fact.name, raw_name=fact.value[:200],
                                          normalized_name=normalize_offering(fact.value), source_id=source.id,
                                          confidence=fact.confidence)
    db.execute(stmt.on_conflict_do_update(
        constraint="uq_company_products_services_name",
        set_={"confidence": func.greatest(CompanyOffering.confidence, stmt.excluded.confidence),
              "source_id": stmt.excluded.source_id, "updated_at": func.now()}))


def save_facts(db: Session, company: Company, source: Source, facts: list[Fact], now: datetime,
               country: str) -> int:
    """Stores the facts of one page (offerings are saved separately, after the site-wide filter)."""
    for fact in facts:
        row = evidence(db, source, company, fact, now)
        if fact.kind == "phone":
            _phone(db, company, fact, source, now)
        elif fact.kind == "email":
            _email(db, company, fact, source, now)
        elif fact.kind == "social" and not getattr(company, SOCIAL_COLUMNS[fact.name]):
            setattr(company, SOCIAL_COLUMNS[fact.name], fact.value)
        elif fact.kind == "location":
            _location(db, company, fact, source, country)
        elif fact.kind == "signal":
            _signal(db, company, fact, source, row, now)
        elif fact.kind == "offering":
            offering(db, company, fact, source)
    db.flush()
    canonical(db, company)
    return len(facts)


def canonical(db: Session, company: Company) -> None:
    for column, fields in CANONICAL.items():
        rows = db.execute(select(Evidence.extracted_value).where(
            Evidence.company_id == company.id, Evidence.field_name.in_(fields))
            .order_by(Evidence.confidence.desc().nulls_last(), Evidence.observed_at.desc().nulls_last(),
                      Evidence.id.desc())).scalars().all()
        if not rows:
            continue
        current = getattr(company, column)
        if current not in (None, "") and str(current) not in rows:
            continue  # typed in by a person: kept
        best = rows[0]
        setattr(company, column, int(best) if column in _INT_COLUMNS else best)
    if company.employee_count_min and company.employee_count_max \
            and company.employee_count_min > company.employee_count_max:
        company.employee_count_max = None  # inconsistent sources: keep the floor, never an impossible range


def conflicts(db: Session, company_id: int) -> list[dict]:
    """Fields whose sources disagree (founded 1994 in a directory, 1996 on the website...)."""
    out = []
    for column in CONFLICT_FIELDS:
        rows = db.execute(select(Evidence.extracted_value, func.max(Evidence.confidence), func.max(Source.name))
                          .join(Source, Source.id == Evidence.source_id)
                          .where(Evidence.company_id == company_id, Evidence.field_name.in_(CANONICAL[column]))
                          .group_by(Evidence.extracted_value)
                          .order_by(func.max(Evidence.confidence).desc())).all()
        if len(rows) > 1:
            out.append({"field": column, "values": [{"value": v, "confidence": c, "source": s} for v, c, s in rows]})
    return out
