"""Deterministic relevance of a company to a search (0-1), the same for known and newly found companies.

    0.30  geography        in the requested city / region (by coordinates, else by address text)
    0.30  industry         normalized industry equal 1.0 · category evidence 0.8 · name only 0.5 · shop 0.3
    0.15  source quality   best quality among the sources that support the company (0-100 -> 0-1)
    0.15  identity         identity confidence: high 1.0 · medium 0.7 · low 0.4 · not assessed 0.5
    0.10  completeness     website, phone, city, industry known

The solution (Odoo / Frinzo / IT) does not take part: discovery does not know yet what a company needs.
"""

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Company, CompanyLocation, Evidence, Source
from app.services.discovery.geography import Area, Country, in_area
from app.services.discovery.industries import NORMALIZED_BY_LABEL, AnyBusinessProfile, label_nodes

_IDENTITY = {"high": 1.0, "medium": 0.7, "low": 0.4, None: 0.5}
_TIER_FIT = {"category": 0.8, "industrial": 0.8, "producer": 0.7, "name": 0.5, "retail_name": 0.3}


@dataclass
class Facts:
    company: Company
    locations: list[CompanyLocation] = field(default_factory=list)
    best_quality: int | None = None


def load_facts(db: Session, companies: list[Company]) -> dict[int, Facts]:
    facts = {c.id: Facts(c) for c in companies}
    if not facts:
        return facts
    ids = list(facts)
    for loc in db.scalars(select(CompanyLocation).where(CompanyLocation.company_id.in_(ids))).all():
        facts[loc.company_id].locations.append(loc)
    rows = db.execute(select(Evidence.company_id, func.max(Source.source_quality))
                      .join(Source, Source.id == Evidence.source_id)
                      .where(Evidence.company_id.in_(ids)).group_by(Evidence.company_id)).all()
    for company_id, quality in rows:
        facts[company_id].best_quality = quality
    return facts


def in_country(f: Facts, country: Country) -> bool:
    names = {country.name.lower(), country.code.lower()}
    return (f.company.headquarters_country or "").lower() in names or \
        any((loc.country or "").lower() in names for loc in f.locations)


def in_requested_area(f: Facts, area: Area | None, country: Country) -> bool:
    if area is None:
        return True
    for loc in f.locations:
        texts = [t for t in (loc.city, loc.region, loc.address) if t]
        if in_area(area, loc.latitude, loc.longitude, texts, country.code):
            return True
    c = f.company
    texts = [t for t in (c.headquarters_city, c.headquarters_region) if t]
    return bool(texts) and in_area(area, None, None, texts, country.code)


def industry_fit(company: Company, profile) -> float:
    """0 = not this industry."""
    if isinstance(profile, AnyBusinessProfile):
        return 1.0
    label = profile.label.lower()
    if (company.industry or "").lower() == label or (company.sub_industry or "").lower() == label:
        return 1.0
    if profile.label in NORMALIZED_BY_LABEL and company.industry in NORMALIZED_BY_LABEL:
        # Both sides normalized and different. A composite (Food & Beverage) still accepts its members' industries.
        if company.industry not in {m.label for m in getattr(profile, "members", ())}:
            return 0.0
    labels = [t for t in (company.industry, company.sub_industry) if t]
    match = profile.score(f"{company.name} {' '.join(labels)}", label_nodes(labels))
    return _TIER_FIT.get(match.tier, 0.0) if match else 0.0


def completeness(c: Company) -> float:
    return sum(bool(v) for v in (c.website, c.primary_phone, c.headquarters_city, c.industry)) / 4


def relevance(f: Facts, profile, area: Area | None, country: Country) -> float:
    geo = 1.0 if in_requested_area(f, area, country) else 0.0
    quality = (f.best_quality if f.best_quality is not None else 50) / 100
    score = (0.30 * geo + 0.30 * industry_fit(f.company, profile) + 0.15 * quality
             + 0.15 * _IDENTITY.get(f.company.identity_confidence, 0.5) + 0.10 * completeness(f.company))
    return round(score, 3)


def ordered(facts: dict[int, Facts], profile, area: Area | None, country: Country) -> list[tuple[Facts, float]]:
    scored = [(f, relevance(f, profile, area, country)) for f in facts.values()]
    return sorted(scored, key=lambda pair: (-pair[1], pair[0].company.name.lower(), pair[0].company.id))

