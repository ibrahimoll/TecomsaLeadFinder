"""Which public sources to look for, for one company: aliases, missing departments, grouped queries.

Deterministic. One identity query ("<company> management team"), then one grouped query per MISSING priority
department, in priority order, within the query budget. Departments already covered by a credible person are not
searched again. Plain words only (no OR / site: syntax assumed); quotes only when the provider supports them.
"""

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, CompanyPerson, Evidence
from app.services.discovery.consolidation import _GENERIC, name_tokens
from app.services.people.titles import fold

PRIORITY = ("executive", "it", "marketing", "finance", "sales", "operations", "hr", "procurement", "supply_chain",
            "customer_experience", "e_commerce", "manufacturing")
TERMS = {
    "executive": "CEO managing director general manager founder",
    "it": "CIO CTO IT manager IT director head of IT",
    "marketing": "marketing director marketing manager CMO",
    "finance": "CFO finance director finance manager",
    "sales": "sales director commercial director sales manager",
    "operations": "COO operations director operations manager",
    "hr": "HR director HR manager human resources",
    "procurement": "procurement manager purchasing manager",
    "supply_chain": "supply chain manager logistics manager",
    "customer_experience": "customer experience manager customer service manager",
    "e_commerce": "e-commerce manager digital director",
    "manufacturing": "plant manager production manager factory manager",
}
_LEGAL = re.compile(r"[\s,.-]*\b(s\.?\s?a\.?\s?l\.?|s\.?\s?a\.?\s?r\.?\s?l\.?|l\.?l\.?c\.?|ltd\.?|inc\.?|co\.?|sal|sarl|"
                    r"s\.a\.|plc|group)\s*$", re.IGNORECASE)
_ARABIC = re.compile(r"[؀-ۿ]")
_PLACES = ("lebanon", "liban", "beirut", "لبنان")


@dataclass
class Query:
    text: str
    departments: tuple[str, ...]  # what it is meant to find ("identity": all of them)


@dataclass
class Plan:
    aliases: list[str]
    missing: list[str]
    queries: list[Query] = field(default_factory=list)


def _distinctive(alias: str) -> bool:
    """Specific enough to identify the company in someone else's text ('ABC Foods' yes, 'Group' / 'Bank' no)."""
    tokens = [t for t in name_tokens(alias) if t not in _GENERIC]
    return bool(tokens) and (len(name_tokens(alias)) >= 2 or len(alias) >= 5) and not all(
        t in ("bank", "group", "company", "hotel", "school", "lebanon", "liban") for t in name_tokens(alias))


def aliases(db: Session, company: Company) -> list[str]:
    """The company's names as others write them: canonical name, without its legal form, the Latin and Arabic
    parts of a bilingual name, its legal / trading names. Too-generic names are left out."""
    names = [company.name, company.legal_name]
    names += db.scalars(select(Evidence.extracted_value).where(Evidence.company_id == company.id,
                                                               Evidence.field_name == "trading_name").distinct())
    found: list[str] = []
    for name in filter(None, names):
        parts = re.split(r"\s+[-–|/]\s+|\s{2,}", name)  # "Laiterie Massabki - ألبان وأجبان مسابكي"
        latin = " ".join(w for w in name.split() if not _ARABIC.search(w))
        arabic = " ".join(w for w in name.split() if _ARABIC.search(w))
        for candidate in (name, *parts, latin, arabic):
            candidate = " ".join(candidate.split()).strip(" -–|,")
            for form in (candidate, _LEGAL.sub("", candidate).strip()):
                if form and _distinctive(form) and fold(form) not in {fold(f) for f in found}:
                    found.append(form)
    return sorted(found, key=lambda a: (bool(_ARABIC.search(a)), -len(a)))[:4]


def covered_departments(db: Session, company_id: int) -> set[str]:
    """Departments with a credible CURRENT person: a not-confirmed (old) role still deserves a search."""
    rows = db.execute(select(CompanyPerson.department, CompanyPerson.employment_status, CompanyPerson.confidence)
                      .where(CompanyPerson.company_id == company_id)).all()
    return {d for d, status, confidence in rows if status == "current" and (confidence or 0) >= 50 and d}


def plan(db: Session, company: Company, *, max_queries: int, quotes: bool) -> Plan:
    names = aliases(db, company)
    missing = [d for d in PRIORITY if d not in covered_departments(db, company.id)]
    result = Plan(names, missing)
    if not names or not missing:
        return result
    main = names[0]
    phrase = f'"{main}"' if quotes else main
    # A short / common name gets the country, a distinctive one does not (over-constraining loses sources).
    if len(name_tokens(main)) <= 2 and not any(p in fold(main) for p in _PLACES):
        phrase += f" {company.headquarters_country or 'Lebanon'}"
    result.queries.append(Query(f"{phrase} management team leadership", tuple(missing)))
    for department in missing:
        if len(result.queries) >= max_queries - 1:
            break
        result.queries.append(Query(f"{phrase} {TERMS[department]}", (department,)))
    if len(result.queries) < max_queries:  # annual reports / brochures name the board and management
        result.queries.append(Query(f"{phrase} annual report board of directors pdf", tuple(missing)))
    return result
