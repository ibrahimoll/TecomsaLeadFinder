"""Candidate normalization and validation, the same for every source.

Normalization never destroys what the source said: the original values are kept in
raw_metadata["original"], the display value stays as written (whitespace tidied), and comparison forms
(normalized name, E.164 phone, domain, folded city) are derived alongside:

    "ABC S.A.L." / "ABC SAL" / "ABC sal" / "ABC Sarl"  -> display unchanged, normalized "abc", legal form kept
    "www.ABCFoods.com.lb/about"                         -> website https://www.ABCFoods.com.lb/about,
                                                           claimed domain abcfoods.com.lb (verified later)
    "01 234 567" in Lebanon                             -> +9611234567
    "Beyrouth" / "بيروت"                                -> city Beirut, region Beirut
"""

import re
from dataclasses import dataclass, field

from app.services.discovery.candidate import CompanyCandidate
from app.services.discovery.consolidation import _GENERIC, name_tokens
from app.services.discovery.domain_resolution import resolve_website
from app.services.discovery.geography import Country, canonical_city, region_for
from app.services.discovery.industries import NON_BUSINESS, NORMALIZED_BY_LABEL, normalize_industry
from app.services.normalization import has_legal_form, normalize_company_name, normalize_phone

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.IGNORECASE)
# A person, not a company: "Dr. Rami Khoury", "Me Nadine Haddad" (Lebanese lawyer title), "د. ...".
_PERSON = re.compile(r"^(dr|doctor|mr|mrs|ms|miss|eng|engineer|prof|me|maître|maitre|sheikh|د|السيد|الدكتور)\b\.?\s",
                     re.IGNORECASE)
_COMPANY_WORDS = re.compile(r"\b(clinic|center|centre|lab|co|company|group|sal|sarl|est|trading|industr|foods?|"
                            r"pharmacy|office|associates|partners|law firm)\b", re.IGNORECASE)


@dataclass
class Normalized:
    """Comparison forms of one candidate (the candidate itself keeps the display values)."""

    candidate: CompanyCandidate
    normalized_name: str
    domain: str | None  # claimed by the source; verified later
    phone: str | None  # E.164 when derivable
    email: str | None
    industry: str  # LeadFinder normalized industry
    social: dict[str, str] = field(default_factory=dict)


def validate(c: CompanyCandidate) -> CompanyCandidate:
    """Reject obviously bad records (sets c.rejected). Closed / wrong-industry are set by the connector."""
    if c.rejected:
        return c
    tokens = name_tokens(c.company_name)
    if not tokens or not any(len(t) >= 2 for t in tokens):
        c.rejected, c.reject_reason = "INVALID", "The record has no usable name."
    elif all(t in _GENERIC for t in tokens):
        c.rejected, c.reject_reason = "INVALID", f"“{c.company_name}” is a generic word, not a company name."
    elif _PERSON.match(c.company_name) and not _COMPANY_WORDS.search(c.company_name):
        c.rejected, c.reject_reason = "NOT_A_BUSINESS", "The record names a person, not a company."
    elif set(c.categories) & NON_BUSINESS:
        c.rejected, c.reject_reason = "NOT_A_BUSINESS", "The source files it as a public / non-business place."
    return c


def normalize(c: CompanyCandidate, country: Country, profile) -> Normalized:
    c.raw_metadata.setdefault("original", {k: v for k, v in {
        "name": c.company_name, "website": c.website, "phone": c.phone, "email": c.email, "city": c.city,
        "region": c.region, "industry": c.industry}.items() if v})
    if has_legal_form(c.company_name) and not c.legal_name:
        c.legal_name = c.company_name  # "ABC Foods S.A.L." is also the legal name
    resolved = resolve_website(c.website)
    c.website = resolved.website
    email = c.email.strip().lower() if c.email and _EMAIL.match(c.email.strip()) else None
    c.email = email
    c.country = country.name
    c.city = canonical_city(country.code, c.latitude, c.longitude, c.city) if c.city or c.latitude else None
    c.region = c.region or region_for(country.code, c.latitude, c.longitude, c.city)
    c.address = " ".join(c.address.split())[:500] if c.address else None
    # The searched industry: the connector only returns records that match it (how strongly is the evidence
    # tier, kept on the industry evidence). A free-text search falls back to the record's own categories.
    searched = profile.label in NORMALIZED_BY_LABEL
    industry = profile.label if searched else normalize_industry(c.company_name, set(c.categories))
    return Normalized(
        candidate=c,
        normalized_name=normalize_company_name(c.company_name) or c.company_name.lower(),
        domain=resolved.domain or (resolve_website(c.domain).domain if c.domain else None),
        phone=normalize_phone(c.phone, country.name),
        email=email,
        industry=industry,
        social=resolved.social,
    )
