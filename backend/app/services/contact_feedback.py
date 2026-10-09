"""Sales feedback (Steps 6.1-6.2): what real business activity showed about a person or a contact point, applied to
the contact graph at once, audited, kept in the contact's evidence trail, and applied ONCE per event (event_key: a
delivery / bounce / reply notification's own id). Nothing here sends anything or probes anyone.

    e-mail   delivered        confidence up; a prediction becomes high_confidence_predicted (still not confirmed)
             hard_bounce      invalid (never shown as a way to reach the person)
             soft_bounce      recorded only (a full mailbox is not a wrong address)
             replied          confirmed (the person answered from it)
             human_confirmed  confirmed by a colleague (provenance human_confirmed: research never changes it)
    phone    number_confirmed verified;  wrong_number invalid;  company_switchboard the company's line, not the
             person's;  extension_confirmed an office extension of the person (both protected from research)
    person   correct_person   current, confirmed;  person_left_company former;  wrong_person not this company's
             person (confidence 0, never a decision-maker);  title_changed the new title, the person's other titles
             at the company kept as history (former)
    All person verdicts are corrected fields: research never undoes them.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessRuleError, NotFoundError
from app.models import CompanyPerson, ContactEvidence, ContactFeedback, Email, Phone, User
from app.models.people import FEEDBACK_EVENTS
from app.services import audit_service

EMAIL_EVENTS = {"delivered", "hard_bounce", "soft_bounce", "replied", "human_confirmed"}
PHONE_EVENTS = {"number_confirmed", "wrong_number", "company_switchboard", "extension_confirmed"}
PERSON_EVENTS = {"correct_person", "wrong_person", "person_left_company", "title_changed"}
PROTECTED = ("human_confirmed", "internal_crm")


def _owned(db: Session, model, row_id: int | None, company_id: int, what: str):
    row = db.get(model, row_id) if row_id else None
    if row is None or row.company_id != company_id:
        raise NotFoundError(f"{what} not found at this company")
    return row


def _correct(role: CompanyPerson, user: User, now: datetime, **fields) -> dict:
    before = {k: getattr(role, k) for k in fields}
    for key, value in fields.items():
        setattr(role, key, value)
    if "employment_status" in fields:
        role.is_current = role.employment_status == "current"
    role.corrected_fields = sorted(set(role.corrected_fields or []) | set(fields))
    role.corrected_by_user_id, role.corrected_at = user.id, now
    return {k: [str(before[k]), str(getattr(role, k))] for k in fields}


def _email(email: Email, event: str, now: datetime) -> dict:
    before = email.status
    if event == "delivered":
        email.confidence = min(95, (email.confidence or 50) + 10)
        if email.status == "predicted":
            email.status = "high_confidence_predicted"
        email.verification = {**(email.verification or {}),
                              "delivered": (email.verification or {}).get("delivered", 0) + 1}
    elif event == "hard_bounce" and email.provenance not in PROTECTED:
        email.status, email.confidence, email.last_verified_at = "invalid", 0, None
    elif event in ("replied", "human_confirmed"):
        email.status, email.confidence, email.last_verified_at = "confirmed", 98, now
        if event == "human_confirmed":
            email.provenance = "human_confirmed"
    email.verification = {**(email.verification or {}), "last_event": event, "last_event_at": now.isoformat()}
    return {"status": [before, email.status], "confidence": email.confidence}


def record_feedback(db: Session, user: User, company_id: int, event: str, *, email_id: int | None = None,
                    phone_id: int | None = None, company_person_id: int | None = None, value: str | None = None,
                    note: str | None = None, event_key: str | None = None) -> tuple[ContactFeedback, bool]:
    """(the event, whether it was applied now): an event already received (same event_key) is not applied again."""
    if event not in FEEDBACK_EVENTS:
        raise BusinessRuleError(f"event must be one of {', '.join(FEEDBACK_EVENTS)}")
    if event_key and (seen := db.scalar(select(ContactFeedback).where(ContactFeedback.event_key == event_key))):
        return seen, False
    now = datetime.now(timezone.utc)
    person_id, effect, contact = None, {}, None
    if event in EMAIL_EVENTS:
        contact = _owned(db, Email, email_id, company_id, "E-mail")
        person_id, effect = contact.person_id, _email(contact, event, now)
    elif event in PHONE_EVENTS:
        contact = _owned(db, Phone, phone_id, company_id, "Phone")
        person_id = contact.person_id
        before = [contact.status, contact.phone_type]
        if event == "number_confirmed":
            contact.status, contact.last_verified_at = "verified", now
        elif event == "wrong_number":
            contact.status = "invalid"
        elif event == "company_switchboard":
            contact.phone_type, contact.provenance = "company_switchboard", "human_confirmed"
        elif event == "extension_confirmed":
            contact.phone_type, contact.status, contact.last_verified_at = "office_extension", "verified", now
            contact.provenance = "human_confirmed"
        effect = {"before": before, "after": [contact.status, contact.phone_type]}
    else:
        role = _owned(db, CompanyPerson, company_person_id, company_id, "Person")
        person_id = role.person_id
        if event == "correct_person":
            effect = _correct(role, user, now, employment_status="current")
            role.last_verified_at = now
        elif event == "person_left_company":
            effect = _correct(role, user, now, employment_status="former")
        elif event == "wrong_person":
            effect = _correct(role, user, now, confidence=0, employment_status="unknown")
        else:
            if not (value or "").strip():
                raise BusinessRuleError("title_changed needs the new title")
            effect = _correct(role, user, now, job_title=value.strip()[:300], employment_status="current")
            role.last_verified_at = now
            for other in db.scalars(select(CompanyPerson).where(  # the earlier titles: history, not current
                    CompanyPerson.company_id == company_id, CompanyPerson.person_id == person_id,
                    CompanyPerson.id != role.id, CompanyPerson.employment_status == "current")):
                _correct(other, user, now, employment_status="former")
                effect.setdefault("earlier_titles", []).append(other.job_title)
    row = ContactFeedback(event=event, company_id=company_id, person_id=person_id, company_person_id=company_person_id,
                          email_id=email_id, phone_id=phone_id, value=(value or None) and value[:320],
                          note=(note or None) and note[:500], effect=effect, user_id=user.id, event_key=event_key)
    db.add(row)
    db.flush()
    if contact is not None:
        db.add(ContactEvidence(email_id=email_id, phone_id=phone_id, kind=event, feedback_id=row.id, user_id=user.id,
                               detail=(note or "")[:300] or None, observed_at=now))
    audit_service.record(db, action=f"contact_feedback.{event}", user_id=user.id,
                         entity_type="email" if email_id else "phone" if phone_id else "company_person",
                         entity_id=email_id or phone_id or company_person_id,
                         metadata={"company_id": company_id, "person_id": person_id, "effect": effect,
                                   "event_key": event_key})
    db.commit()
    return row, True


def record_email_event(db: Session, user: User, address: str, event: str, *, event_key: str | None = None) -> int:
    """A mail system's delivery / bounce / reply notification for an address (no company known): applied to every
    LeadFinder record of that address. Returns how many records it applied to (0: unknown address or a repeat)."""
    if event not in ("delivered", "hard_bounce", "soft_bounce", "replied"):
        raise BusinessRuleError("only delivered / hard_bounce / soft_bounce / replied arrive by address")
    applied = 0
    rows = db.scalars(select(Email).where(Email.email == address.strip().lower(), Email.company_id.is_not(None))).all()
    for i, email in enumerate(rows):
        key = f"{event_key}:{i}" if event_key else None
        _, done = record_feedback(db, user, email.company_id, event, email_id=email.id, event_key=key)
        applied += done
    return applied
