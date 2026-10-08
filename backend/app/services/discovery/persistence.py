"""Writes a consolidated, resolved company: SOURCE -> EVIDENCE -> master data.

* A new company is created once; an existing one is never overwritten, only completed (blank fields).
* Every source record becomes (or reuses) one `sources` row: the same record seen again with the same
  content is not stored twice; a changed record (new dataset release) is a new source row.
* Every material claim becomes evidence (name, industry, website, phone, email, address, size,
  registration number), with the source's quality as confidence. Repeats are not duplicated.
* Each source record's id is kept in company_identifiers, which is what makes discovery idempotent.
"""

import hashlib
import json
import math
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import (Company, CompanyIdentifier, CompanyLocation, Email, Evidence, Phone, PossibleDuplicate,
                        Source)
from app.models.enums import IdentityConfidence
from app.services.discovery.candidate import CompanyCandidate, ConnectorConfig
from app.services.discovery.consolidation import SAME_PLACE_KM, Assessment, Group
from app.services.discovery.deduplication import Resolution, identifiers
from app.services.discovery.geography import Country
from app.services.discovery.normalizer import Normalized
from app.services.normalization import normalize_company_name

_RANK = {None: 0, IdentityConfidence.LOW: 1, IdentityConfidence.MEDIUM: 2, IdentityConfidence.HIGH: 3}  # str keys too
_TIER_CONFIDENCE = {"category": 1.0, "industrial": 0.9, "producer": 0.8, "name": 0.5, "retail_name": 0.4}


def _hash(c: CompanyCandidate) -> str:
    payload = {"connector": c.connector, "id": c.external_id, "name": c.company_name, "raw": c.raw_metadata}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def upsert_source(db: Session, c: CompanyCandidate, config: ConnectorConfig, version: str | None) -> Source:
    digest = _hash(c)
    existing = db.scalar(select(Source).where(Source.content_hash == digest, Source.source_type == c.source_type,
                                              Source.external_reference == c.external_id).limit(1))
    if existing:
        return existing
    source = Source(source_type=c.source_type, name=c.source_name[:300], url=c.source_url,
                    external_reference=(c.external_id or "")[:300] or None,
                    publisher=c.raw_metadata.get("publisher") or config.label, retrieved_at=c.observed_at,
                    source_quality=config.quality, content_hash=digest,
                    metadata_={"connector": c.connector, "dataset_version": version, "raw": c.raw_metadata})
    db.add(source)
    db.flush()
    return source


def _evidence(db: Session, source: Source, company: Company, field: str, value, confidence: float,
              structured=None, excerpt: str | None = None) -> None:
    if value in (None, ""):
        return
    value = str(value)[:2000]
    exists = db.scalar(select(Evidence.id).where(Evidence.source_id == source.id, Evidence.company_id == company.id,
                                                 Evidence.field_name == field, Evidence.extracted_value == value))
    if exists:
        return
    db.add(Evidence(source_id=source.id, company_id=company.id, evidence_type="company_fact", field_name=field,
                    extracted_value=value, excerpt=excerpt, structured_value=structured,
                    confidence=max(0, min(100, round(confidence))), observed_at=source.retrieved_at))


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def _add_location(db: Session, company: Company, c: CompanyCandidate, source: Source, confidence: int) -> None:
    """One row per distinct place: within 500 m (or the same city + address) is the same place."""
    for loc in db.scalars(select(CompanyLocation).where(CompanyLocation.company_id == company.id)).all():
        if None not in (loc.latitude, loc.longitude, c.latitude, c.longitude):
            if _km((loc.latitude, loc.longitude), (c.latitude, c.longitude)) <= SAME_PLACE_KM:
                return
        elif (loc.city or "").lower() == (c.city or "").lower() and (loc.address or "") == (c.address or ""):
            return
    db.add(CompanyLocation(company_id=company.id, location_type="branch" if c.brand else None,
                           country=c.country or "", region=c.region, city=c.city, address=c.address,
                           latitude=c.latitude, longitude=c.longitude, source_id=source.id, confidence=confidence))


def _identity(company: Company, assessment: Assessment, sources_cited: int) -> str:
    """Never lowered by a weaker new record; several independent sources lift LOW to MEDIUM."""
    level = max(company.identity_confidence, assessment.confidence.value, key=lambda v: _RANK[v])
    if sources_cited >= 2 and level == IdentityConfidence.LOW:
        level = IdentityConfidence.MEDIUM.value
    return level


def save(db: Session, *, group: Group, norms: dict[int, Normalized], resolution: Resolution, assessment: Assessment,
         country: Country, configs: dict[str, ConnectorConfig], versions: dict[str, str | None],
         user_id: int | None) -> tuple[Company, bool]:
    """Create or complete the canonical company for one consolidated group. Returns (company, is_new)."""
    merged = group.merged()
    first = norms[id(group.primary)]
    company, is_new = resolution.company, resolution.company is None
    if company is None:
        company = Company(name=group.name[:300], normalized_name=normalize_company_name(group.name) or group.name.lower(),
                          status="new", created_by_user_id=user_id, headquarters_country=country.name)
        db.add(company)
    social = {k: v for c in group.records for k, v in norms[id(c)].social.items()}
    phone = next((c.phone for c in group.records if norms[id(c)].phone), None)
    email = next((norms[id(c)].email for c in group.records if norms[id(c)].email), None)
    for field, value in {
        "legal_name": merged.legal_name, "website": merged.website, "description": merged.description,
        "industry": first.industry, "sub_industry": (merged.industry or "")[:120] or None,
        "employee_count_estimate": merged.employee_count, "headquarters_country": country.name,
        "headquarters_region": merged.region, "headquarters_city": merged.city, "primary_phone": phone,
        "primary_email": email, **social,
    }.items():
        if getattr(company, field) in (None, "") and value not in (None, ""):
            setattr(company, field, value)
    if company.industry == "Other" and first.industry != "Other":
        company.industry = first.industry  # a specific industry beats the fallback
    db.flush()

    connectors_cited = set()
    for c in group.records:
        n, config = norms[id(c)], configs[c.connector]
        source = upsert_source(db, c, config, versions.get(c.connector))
        connectors_cited.add(c.connector)
        for scheme, value in identifiers(c, n, country.code):
            db.execute(insert(CompanyIdentifier).values(company_id=company.id, scheme=scheme, value=value,
                                                        source_id=source.id).on_conflict_do_nothing())
        quality = config.quality
        _evidence(db, source, company, "name", c.company_name, quality, excerpt=c.raw_metadata.get("name"))
        _evidence(db, source, company, "industry", n.industry, quality * _TIER_CONFIDENCE.get(c.tier, 0.5),
                  structured={"source_category": c.industry, "categories": c.categories, "tier": c.tier,
                              "reason": c.match_reason})
        _evidence(db, source, company, "website", c.website, quality)
        _evidence(db, source, company, "phone", n.phone or c.phone, quality)
        _evidence(db, source, company, "email", n.email, quality)
        _evidence(db, source, company, "address", ", ".join(p for p in (c.address, c.city, c.region) if p), quality,
                  structured={"lat": c.latitude, "lon": c.longitude} if c.latitude is not None else None)
        _evidence(db, source, company, "employee_count", c.employee_count, quality * 0.7)
        _evidence(db, source, company, "registration_number", c.registration_number, quality)
        if any(c is place for place in group.locations):
            _add_location(db, company, c, source, quality)
        if n.phone and not db.scalar(select(Phone.id).where(Phone.company_id == company.id, Phone.person_id.is_(None),
                                                             Phone.normalized_phone == n.phone)):
            db.add(Phone(company_id=company.id, phone=c.phone[:50], normalized_phone=n.phone, phone_type="unknown",
                         is_public=True, status="discovered", confidence=quality, source_id=source.id,
                         first_seen_at=c.observed_at, last_seen_at=c.observed_at))
        if n.email and not db.scalar(select(Email.id).where(Email.company_id == company.id, Email.person_id.is_(None),
                                                             Email.email == n.email)):
            db.add(Email(company_id=company.id, email=n.email, email_type="generic", is_public=True,
                         status="published", confidence=quality, source_id=source.id, first_seen_at=c.observed_at,
                         last_seen_at=c.observed_at))
        db.flush()

    known_schemes = set(db.scalars(select(CompanyIdentifier.scheme).where(CompanyIdentifier.company_id == company.id)))
    company.identity_confidence = _identity(company, assessment, len(known_schemes - {"web"} | connectors_cited))
    for other, reason in resolution.possible:  # stored once per pair (lower id first)
        if other.id != company.id:
            low, high = sorted((company.id, other.id))
            db.execute(insert(PossibleDuplicate).values(company_id=low, other_company_id=high,
                                                        reason=reason[:300]).on_conflict_do_nothing())
    company.updated_at = datetime.now(timezone.utc)
    return company, is_new
