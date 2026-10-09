"""Privacy controls (Law 81/2018, GDPR-style obligations for a contact database).

    removal     a person removed on request (`forget_person`): the person, roles, emails, phones and evidence are
                deleted; a suppression (hash of company + name key, never the name) stops research and imports from
                adding them again at that company (`is_suppressed`, checked in people.persistence.save)
    retention   `purge_expired`: a publicly researched role no source has seen for CONTACT_RETENTION_DAYS is deleted,
                then every person left without a role (with their contacts). TECOMSA's own data (Odoo, contributed),
                colleague corrections and confirmations are kept. Runs daily in the worker.
"""

import hashlib
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import NotFoundError
from app.models import CompanyPerson, Email, Person, PersonSuppression, Phone, User
from app.services import audit_service
from app.services.people.names import name_key

logger = logging.getLogger("leadfinder.privacy")
PROTECTED = ("internal_crm", "contributed", "human_confirmed")  # TECOMSA's own / a colleague's: never expired


def _key_hash(company_id: int, full_name: str) -> str | None:
    key = name_key(full_name or "")  # folded, particles dropped, the first name in its canonical form
    return hashlib.sha256(f"{company_id}:{' '.join(key)}".encode()).hexdigest() if key else None


def is_suppressed(db: Session, company_id: int, full_name: str) -> bool:
    key = _key_hash(company_id, full_name)
    return key is not None and db.scalar(select(exists().where(PersonSuppression.company_id == company_id,
                                                               PersonSuppression.key_hash == key)))


def forget_person(db: Session, user: User, company_id: int, person_id: int, reason: str) -> dict:
    person = db.get(Person, person_id)
    companies = set(db.scalars(select(CompanyPerson.company_id).where(CompanyPerson.person_id == person_id)))
    if person is None or company_id not in companies:
        raise NotFoundError("Person not found at this company")
    for cid in companies:  # every company LeadFinder linked them to
        if key := _key_hash(cid, person.full_name):
            db.execute(insert(PersonSuppression).values(company_id=cid, key_hash=key, reason=reason[:300],
                                                        requested_by_user_id=user.id).on_conflict_do_nothing())
    db.delete(person)  # cascades: roles, emails, phones, contact evidence, evidence, possible duplicates
    audit_service.record(db, action=audit_service.AuditAction.PERSON_REMOVED, user_id=user.id, entity_type="person",
                         entity_id=person_id, metadata={"company_ids": sorted(companies), "reason": reason[:300]})
    db.commit()
    return {"removed": True, "companies": len(companies)}


def purge_expired(db: Session, now: datetime | None = None) -> dict:
    days = get_settings().contact_retention_days
    if days <= 0:
        return {"roles": 0, "people": 0}
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    seen = func.coalesce(func.greatest(CompanyPerson.last_seen_at, CompanyPerson.last_verified_at),
                         CompanyPerson.first_seen_at, CompanyPerson.created_at)
    def protected(person_id):
        return or_(*(exists().where(m.person_id == person_id, m.provenance.in_(PROTECTED)) for m in (Email, Phone)))
    roles = db.execute(delete(CompanyPerson).where(
        seen < cutoff, CompanyPerson.owner_user_id.is_(None), CompanyPerson.corrected_fields.is_(None),
        ~protected(CompanyPerson.person_id)).execution_options(synchronize_session=False)).rowcount
    people = db.execute(delete(Person).where(~exists().where(CompanyPerson.person_id == Person.id),
                                             ~protected(Person.id))
                        .execution_options(synchronize_session=False)).rowcount
    db.commit()
    if roles or people:
        logger.info("retention: %s role(s) and %s person(s) not seen for %s days deleted", roles, people, days)
    return {"roles": roles, "people": people}
