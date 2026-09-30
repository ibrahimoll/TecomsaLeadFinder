"""Deterministic company matching (duplicate protection foundation).

Signals, strongest first:
  1. Odoo partner id        exact   1.00
  2. Website domain         strong  0.95
  3. Company email domain   strong  0.90
  4. Phone (E.164)          strong  0.90
  5. Name + city            medium  0.80
  6. Normalised name        medium  0.70

Phase 1 can add fuzzy or learned matching behind the same `find_matches` interface.
"""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company
from app.services.normalization import (
    email_domain,
    normalize_company_name,
    normalize_domain,
    normalize_phone,
)


@dataclass
class MatchSignals:
    name: str | None = None
    website: str | None = None
    email: str | None = None
    phone: str | None = None
    city: str | None = None
    country: str | None = None
    odoo_contact_id: int | None = None

    # Derived, computed once.
    normalized_name: str | None = field(init=False, default=None)
    domain: str | None = field(init=False, default=None)
    email_domain: str | None = field(init=False, default=None)
    phone_normalized: str | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self.normalized_name = normalize_company_name(self.name) if self.name else None
        self.domain = normalize_domain(self.website) if self.website else None
        self.email_domain = email_domain(self.email)
        self.phone_normalized = normalize_phone(self.phone, self.country)


@dataclass
class CompanyMatch:
    company: Company
    score: float
    reasons: list[str]

    @property
    def reason(self) -> str:
        return "; ".join(self.reasons)


def find_matches(
    db: Session, signals: MatchSignals, *, exclude_id: int | None = None, limit: int = 5
) -> list[CompanyMatch]:
    """Existing companies that may be the same organisation, best first."""
    found: dict[int, CompanyMatch] = {}

    def add(companies, score: float, reason: str) -> None:
        for company in companies:
            if company.id == exclude_id:
                continue
            match = found.get(company.id)
            if match is None:
                found[company.id] = CompanyMatch(company, score, [reason])
            else:
                match.score = max(match.score, score)
                if reason not in match.reasons:
                    match.reasons.append(reason)

    def query(*conditions):
        return db.scalars(select(Company).where(*conditions).limit(limit * 2)).all()

    if signals.odoo_contact_id:
        add(query(Company.odoo_contact_id == signals.odoo_contact_id), 1.0,
            f"Same Odoo partner #{signals.odoo_contact_id}")
    if signals.domain:
        add(query(Company.domain == signals.domain), 0.95, f"Same website domain ({signals.domain})")
        add(query(Company.email_domain == signals.domain), 0.9, f"Email domain matches website ({signals.domain})")
    if signals.email_domain:
        add(query(Company.email_domain == signals.email_domain), 0.9,
            f"Same email domain ({signals.email_domain})")
        add(query(Company.domain == signals.email_domain), 0.9,
            f"Email domain matches website ({signals.email_domain})")
    if signals.phone_normalized:
        add(query(Company.main_phone_normalized == signals.phone_normalized), 0.9,
            f"Same phone number ({signals.phone_normalized})")
    if signals.normalized_name:
        same_name = query(Company.normalized_name == signals.normalized_name)
        if signals.city:
            city = signals.city.strip().lower()
            add([c for c in same_name if (c.city or "").strip().lower() == city], 0.8,
                f"Same name and city ({signals.normalized_name}, {signals.city})")
        add(same_name, 0.7, f"Same normalised name ({signals.normalized_name})")

    return sorted(found.values(), key=lambda m: (-m.score, m.company.id))[:limit]


class CompanyIndex:
    """In-memory version of `find_matches` for bulk imports (same signals and scores).

    Name-only matches are accepted because Odoo exports often carry nothing but the
    company name. On ties the oldest company wins, so an import never adds yet another
    copy of an already-duplicated company.
    """

    def __init__(self, companies):
        self._by: dict[tuple[str, object], list[Company]] = {}
        for company in sorted(companies, key=lambda c: c.id or 0):
            self.add(company)

    def add(self, company: Company) -> None:
        for key in (("partner", company.odoo_contact_id), ("domain", company.domain),
                    ("email_domain", company.email_domain), ("phone", company.main_phone_normalized),
                    ("name", company.normalized_name)):
            if key[1]:
                self._by.setdefault(key, []).append(company)

    def match(self, s: MatchSignals) -> CompanyMatch | None:
        checks = [
            (("partner", s.odoo_contact_id), 1.0, "Same Odoo partner"),
            (("domain", s.domain), 0.95, "Same website domain"),
            (("email_domain", s.domain), 0.9, "Email domain matches website"),
            (("email_domain", s.email_domain), 0.9, "Same email domain"),
            (("domain", s.email_domain), 0.9, "Email domain matches website"),
            (("phone", s.phone_normalized), 0.9, "Same phone number"),
        ]
        for key, score, reason in checks:
            if key[1] and self._by.get(key):
                return CompanyMatch(self._by[key][0], score, [reason])
        same_name = self._by.get(("name", s.normalized_name), []) if s.normalized_name else []
        if same_name:
            city = (s.city or "").strip().lower()
            for company in same_name:
                if city and (company.city or "").strip().lower() == city:
                    return CompanyMatch(company, 0.8, ["Same name and city"])
            return CompanyMatch(same_name[0], 0.7, ["Same normalised name"])
        return None
