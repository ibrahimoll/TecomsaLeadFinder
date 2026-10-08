"""Company matching, confidence and person entity resolution.

Resolution is per company: a candidate is compared with the people LeadFinder already has AT THIS COMPANY.

    same explicitly published email (any company)              -> same person
    identical name (after honorifics) + compatible role area   -> same person
    a known form of the name (Joe / Joseph) + same department  -> same person
    an initial ("J. Haddad") + the same normalized title       -> same person
    anything weaker (Johnny / John, same name but other role)  -> a NEW person, flagged as a possible duplicate

Never merged on a name alone, never across companies on a name alone (John Smith at A is not John Smith at B).
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CompanyPerson, Email, Person
from app.services.people.candidate import PersonCandidate
from app.services.people.names import clean_name, name_key
from app.services.people.titles import fold

MIN_COMPANY_MATCH = 60  # below this a source does not tie the person to the company: never stored
WEAK = 50  # below this a role is never shown as current


def confidence(c: PersonCandidate, now: datetime | None = None) -> tuple[int, dict]:
    """0-100 with its parts (stored on the role): the weakest of source and company match, scaled by how explicit
    the title is, how recent the evidence is and how certain the current / former status is. Confirmation by
    other sources is added when the role is recomputed (persistence.recompute)."""
    age = ((now or datetime.now(timezone.utc)) - c.observed_at).days
    parts = {
        "source": c.source_confidence,
        "company_match": c.company_match_confidence,
        "title": 1.0 if c.title_explicit else 0.85,
        "recency": 1.0 if age <= 30 else 0.9 if age <= 180 else 0.75,
        "status": {"current": 1.0, "former": 0.95}.get(c.status, 0.8),
    }
    score = min(parts["source"], parts["company_match"]) * parts["title"] * parts["recency"] * parts["status"]
    return round(score), parts


@dataclass
class Match:
    person: Person | None
    reason: str
    possible: list[Person] = field(default_factory=list)


def _first_last(key: tuple[str, ...]) -> tuple[str, str]:
    return key[0], key[-1]


def resolve(db: Session, company_id: int, c: PersonCandidate) -> Match:
    if c.email:
        owner = db.scalar(select(Person).join(Email, Email.person_id == Person.id).where(Email.email == c.email)
                          .limit(1))
        if owner is not None:
            return Match(owner, "same published email")
    key = name_key(c.full_name)
    literal = fold(clean_name(c.full_name))
    rows = db.execute(select(Person, CompanyPerson.department, CompanyPerson.normalized_title)
                      .join(CompanyPerson, CompanyPerson.person_id == Person.id)
                      .where(CompanyPerson.company_id == company_id)).all()
    people: dict[int, tuple[Person, set, set]] = {}
    for person, department, title in rows:
        entry = people.setdefault(person.id, (person, set(), set()))
        entry[1].add(department or "other")
        entry[2].add(title)
    possible: list[Person] = []
    for person, departments, titles in people.values():
        other = name_key(person.full_name)
        if not other or not key:
            continue
        same_department = c.department in departments and c.department != "other"
        compatible = same_department or c.department == "other" or departments <= {"other"}
        if fold(clean_name(person.full_name)) == literal:
            if compatible:
                return Match(person, "same name, compatible role")
            possible.append(person)  # same name, different role area: maybe two people
        elif other == key or (_first_last(other) == _first_last(key) and min(len(other), len(key)) == 2):
            if same_department:
                return Match(person, "same name (variant / middle name) and department")
            possible.append(person)
        elif key[-1] == other[-1]:
            a, b = key[0], other[0]
            if (len(a) == 1 or len(b) == 1) and a[0] == b[0]:  # "J. Haddad" / "Joseph Haddad"
                if c.normalized_title and c.normalized_title in titles:
                    return Match(person, "initial and the same title")
                possible.append(person)
            elif a != b and (a.startswith(b) or b.startswith(a)):  # "Johnny" / "John": never merged
                possible.append(person)
    return Match(None, "new person", possible)
