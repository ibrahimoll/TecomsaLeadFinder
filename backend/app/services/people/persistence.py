"""Stores resolved candidates: people (identity) + company_people (the role at this company) + evidence.

* One role row per person and title meaning at a company (normalized title, else the raw title); every source
  that states it adds an evidence row (the raw title it used, the excerpt, the date, the confidence).
* Fields a person corrected by hand (corrected_fields) are never changed by research.
* Public business emails / phones published with the person are stored as `discovered` (never guessed).
* recompute(): confirmation by independent sources raises confidence; weak roles are never shown as current;
  the internal decision-maker coverage of the company is refreshed.
"""

from datetime import datetime
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Company, CompanyPerson, Email, Evidence, Person, Phone, PossibleDuplicatePerson, Source
from app.models.enums import EmailStatus, EmploymentStatus, PhoneStatus
from app.services.people.candidate import PersonCandidate
from app.services.people.names import name_key
from app.services.people.resolution import WEAK, Match, confidence
from app.services.people.titles import fold

# Departments whose decision-maker coverage is tracked (internal; not a quality score).
PRIORITY_DEPARTMENTS = ("executive", "it", "marketing", "finance", "sales", "hr", "operations", "procurement")
_PROTECTABLE = ("job_title", "department", "seniority", "employment_status")


def _role_key(normalized: str | None, raw: str) -> str:
    return fold(normalized or raw)


def _set(role: CompanyPerson, field: str, value) -> None:
    if field not in (role.corrected_fields or []):
        setattr(role, field, value)


def _status(role: CompanyPerson, status: str) -> None:
    if "employment_status" not in (role.corrected_fields or []):
        role.employment_status = status
        role.is_current = status == EmploymentStatus.CURRENT


def save(db: Session, company: Company, c: PersonCandidate, match: Match, now: datetime) -> CompanyPerson:
    person = match.person
    if person is None:
        person = Person(full_name=c.full_name[:300], first_name=(c.first_name or "")[:150] or None,
                        last_name=(c.last_name or "")[:150] or None,
                        normalized_name=" ".join(name_key(c.full_name))[:300], profile_url=c.profile_url)
        db.add(person)
        db.flush()
    elif c.profile_url and not person.profile_url:
        person.profile_url = c.profile_url
    score, parts = confidence(c, now)
    key = _role_key(c.normalized_title, c.raw_title or "")
    role = next((r for r in db.scalars(select(CompanyPerson).where(CompanyPerson.company_id == company.id,
                                                                    CompanyPerson.person_id == person.id))
                 # the same published title is the same role, whatever an older taxonomy normalised it to
                 if _role_key(r.normalized_title, r.job_title) == key or r.job_title == (c.raw_title or "")[:300]),
                None)
    if role is None:
        role = CompanyPerson(company_id=company.id, person_id=person.id, job_title=(c.raw_title or "")[:300],
                             normalized_title=c.normalized_title, department=c.department, seniority=c.seniority,
                             title_rank=c.title_rank, employment_status=c.status,
                             is_current=c.status == EmploymentStatus.CURRENT, started_at=c.started_at,
                             ended_at=c.ended_at, confidence=score, confidence_components={**parts, "base": score},
                             first_seen_at=now, primary_source_id=c.source_id)
        db.add(role)
    elif "confidence" not in (role.corrected_fields or []):  # a person's verdict (wrong person) is never undone
        base = max((role.confidence_components or {}).get("base", 0), score)
        role.confidence_components = {**parts, "base": base}
        if c.status == EmploymentStatus.CURRENT or role.employment_status == EmploymentStatus.UNKNOWN:
            _status(role, c.status)  # a current statement wins; former / unknown never erase a current one
        elif c.status == EmploymentStatus.FORMER and c.observed_at >= (role.last_seen_at or c.observed_at):
            _status(role, c.status)
        role.started_at = role.started_at or c.started_at
        role.ended_at = role.ended_at or c.ended_at
        if score > (role.confidence or 0):
            role.primary_source_id = c.source_id
    _set(role, "department", role.department or c.department)
    _set(role, "seniority", role.seniority or c.seniority)
    role.title_rank = role.title_rank or c.title_rank
    role.last_seen_at = now
    if c.status == EmploymentStatus.CURRENT:
        role.last_verified_at = now
    db.flush()
    _evidence(db, company, person, role, c, score, match)
    _contacts(db, company, person, c, score, now)
    for other in match.possible:
        low, high = sorted((person.id, other.id))
        if low != high and not db.scalar(select(PossibleDuplicatePerson.id).where(
                PossibleDuplicatePerson.person_id == low, PossibleDuplicatePerson.other_person_id == high)):
            db.add(PossibleDuplicatePerson(company_id=company.id, person_id=low, other_person_id=high,
                                           reason=f"Similar names at the same company: {c.full_name}"[:300]))
    return role


def _evidence(db: Session, company: Company, person: Person, role: CompanyPerson, c: PersonCandidate, score: int,
              match: Match) -> None:
    value = f"{c.full_name} — {c.raw_title}"[:2000]
    if db.scalar(select(Evidence.id).where(Evidence.source_id == c.source_id, Evidence.company_person_id == role.id,
                                           Evidence.extracted_value == value)):
        return
    db.add(Evidence(source_id=c.source_id, company_id=company.id, person_id=person.id, company_person_id=role.id,
                    evidence_type="employment", field_name="role", extracted_value=value,
                    excerpt=c.evidence_excerpt, confidence=score, observed_at=c.observed_at,
                    structured_value={"status": c.status, "source_type": c.source_type, "resolution": match.reason,
                                      "raw_title": c.raw_title, "biography": c.biography,
                                      "page": c.raw_metadata.get("page"),
                                      "category": c.raw_metadata.get("category"),
                                      "started": c.started_at.isoformat() if c.started_at else None,
                                      "ended": c.ended_at.isoformat() if c.ended_at else None}))


def _contacts(db: Session, company: Company, person: Person, c: PersonCandidate, score: int, now: datetime) -> None:
    """A business email / phone the source publishes in the person's own entry (contact_intelligence classifies
    the phone later: mobile / direct / extension / the company's switchboard)."""
    evidence = f"published with the person's entry: {(c.source_url or '')[:200]}"
    if c.email and not db.scalar(select(Email.id).where(Email.person_id == person.id, Email.email == c.email)):
        db.add(Email(person_id=person.id, company_id=company.id, email=c.email, email_type="work",
                     status=EmailStatus.PUBLISHED.value, is_public=True, confidence=score, source_id=c.source_id,
                     first_seen_at=now, last_seen_at=now, provenance="public", evidence=evidence))
    if c.phone and not db.scalar(select(Phone.id).where(Phone.person_id == person.id,
                                                        Phone.normalized_phone == c.phone)):
        from app.services.contact_intelligence import classify_phone

        context = (c.raw_metadata or {}).get("context") or ""
        db.add(Phone(person_id=person.id, company_id=company.id, phone=c.phone, normalized_phone=c.phone,
                     phone_type=classify_phone(c.phone, company_numbers=set(), context=context[:300]),
                     status=PhoneStatus.DISCOVERED.value, is_public=True, confidence=score,
                     source_id=c.source_id, first_seen_at=now, last_seen_at=now, provenance="public",
                     evidence=f"{evidence} {context[:200]}"[:500]))
    db.flush()


def _origin(excerpt: str | None, url: str | None) -> str:
    """Independent origin of a confirmation: a long passage repeated word for word on several sites is one
    syndicated text (a copied press release), not several confirmations; otherwise one per publisher domain."""
    text = " ".join(fold(excerpt or "").split())
    return f"text:{text[:200]}" if len(text) >= 50 else f"site:{(urlsplit(url or '').hostname or '').removeprefix('www.')}"


def recompute(db: Session, company: Company) -> dict:
    """Confirmation bonus, weak-role guard and coverage, from all the company's role evidence."""
    origins: dict[int, set[str]] = {}
    external_roles: set[int] = set()
    for role_id, excerpt, url, source_type in db.execute(
            select(Evidence.company_person_id, Evidence.excerpt, Source.url, Source.source_type)
            .join(Source, Source.id == Evidence.source_id)
            .where(Evidence.company_id == company.id, Evidence.company_person_id.is_not(None))):
        origins.setdefault(role_id, set()).add(_origin(excerpt, url))
        if source_type != "company_website":
            external_roles.add(role_id)
    sources = {role_id: len(keys) for role_id, keys in origins.items()}
    roles = db.scalars(select(CompanyPerson).where(CompanyPerson.company_id == company.id)).all()
    for role in roles:
        if role.confidence_components is None or "confidence" in (role.corrected_fields or []):
            continue  # typed in / judged by a person: no research confidence
        n = sources.get(role.id, 1)
        base = role.confidence_components.get("base", role.confidence or 0)
        role.confidence = min(98, base + 5 * (n - 1))
        role.confidence_components = {**role.confidence_components, "sources": n}
        if role.confidence < WEAK and role.employment_status == EmploymentStatus.CURRENT:
            _status(role, EmploymentStatus.UNKNOWN.value)  # weak evidence never makes a current employee
    found = {d: any(r.department == d and r.employment_status == EmploymentStatus.CURRENT for r in roles)
             for d in PRIORITY_DEPARTMENTS}
    credible = [r for r in roles if r.employment_status != EmploymentStatus.FORMER and (r.confidence or 0) >= WEAK]
    departments = sorted({r.department for r in credible if r.department})
    external_people = {r.person_id for r in credible if r.id in external_roles}
    company.people_coverage = {
        **(company.people_coverage or {}), **found, "found": sum(found.values()), "of": len(PRIORITY_DEPARTMENTS),
        "people": len({r.person_id for r in roles}),
        "website_people": len({r.person_id for r in credible if r.id not in external_roles}),
        "external_people": len(external_people),
        "departments_found": departments,
        "departments_missing": [d for d in PRIORITY_DEPARTMENTS if d not in departments],
        "source_scope": "website + external" if external_people else "website",
    }
    return company.people_coverage


def mark_absent(db: Session, company: Company, url: str, seen_role_ids: set[int]) -> int:
    """Roles known only from this page that the page no longer lists: no longer shown as current (status
    unknown: they may have left, or the page changed); never deleted."""
    stale = 0
    for role in db.scalars(select(CompanyPerson).where(CompanyPerson.company_id == company.id,
                                                       CompanyPerson.employment_status == EmploymentStatus.CURRENT,
                                                       CompanyPerson.id.not_in(seen_role_ids or {0}))):
        urls = set(db.scalars(select(Source.url).join(Evidence, Evidence.source_id == Source.id)
                              .where(Evidence.company_person_id == role.id)))
        if urls == {url}:
            _status(role, EmploymentStatus.UNKNOWN.value)
            stale += 1
    return stale
