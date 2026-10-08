"""Sales feedback (Step 6.1): what real business activity showed about a person or a contact point, applied to the
contact graph at once and kept as an event (contact_feedback). Nothing here sends anything or probes anyone: it
only records what a salesperson's own legitimate outreach / call revealed.

    e-mail   delivered        confidence up; a prediction becomes high_confidence_predicted (still not confirmed)
             hard_bounce      invalid (never shown as a way to reach the person)
             soft_bounce      recorded only (a full mailbox is not a wrong address)
             replied          confirmed (the person answered from it): the strongest research-independent status
             human_confirmed  confirmed by a colleague (provenance human_confirmed: research never changes it)
    phone    number_confirmed verified;  wrong_number invalid;  company_switchboard the company's line, not the
             person's;  extension_confirmed an office extension of the person (both protected from research)
    person   correct_person   current, confirmed;  person_left_company former;  title_changed the new title;
             wrong_person     not this company's person (confidence 0, never shown as a decision-maker)
    Person verdicts go through the same correction path as the People tab (corrected fields are research-proof).
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.exceptions import BusinessRuleError, NotFoundError
from app.models import CompanyPerson, ContactFeedback, Email, Phone, User
from app.models.people import FEEDBACK_EVENTS

EMAIL_EVENTS = {"delivered", "hard_bounce", "soft_bounce", "replied", "human_confirmed"}
PHONE_EVENTS = {"number_confirmed", "wrong_number", "company_switchboard", "extension_confirmed"}
PERSON_EVENTS = {"correct_person", "wrong_person", "person_left_company", "title_changed"}


def _owned(db: Session, model, row_id: int | None, company_id: int, what: str):
    row = db.get(model, row_id) if row_id else None
    if row is None or row.company_id != company_id:
        raise NotFoundError(f"{what} not found at this company")
    return row


def _correct(role: CompanyPerson, user: User, **fields) -> dict:
    before = {k: getattr(role, k) for k in fields}
    for key, value in fields.items():
        setattr(role, key, value)
    if "employment_status" in fields:
        role.is_current = role.employment_status == "current"
    role.corrected_fields = sorted(set(role.corrected_fields or []) | set(fields))
    role.corrected_by_user_id, role.corrected_at = user.id, datetime.now(timezone.utc)
    return {k: [str(before[k]), str(getattr(role, k))] for k in fields}


def apply(db: Session, user: User, company_id: int, event: str, *, email_id: int | None = None,
          phone_id: int | None = None, company_person_id: int | None = None, value: str | None = None,
          note: str | None = None) -> ContactFeedback:
    if event not in FEEDBACK_EVENTS:
        raise BusinessRuleError(f"event must be one of {', '.join(FEEDBACK_EVENTS)}")
    now = datetime.now(timezone.utc)
    effect: dict = {}
    person_id = None
    if event in EMAIL_EVENTS:
        email = _owned(db, Email, email_id, company_id, "E-mail")
        person_id = email.person_id
        before = email.status
        if event == "delivered":
            email.confidence = min(95, (email.confidence or 50) + 10)
            if email.status == "predicted":
                email.status = "high_confidence_predicted"
            email.verification = {**(email.verification or {}),
                                  "delivered": (email.verification or {}).get("delivered", 0) + 1}
        elif event == "hard_bounce" and email.provenance not in ("human_confirmed", "internal_crm"):
            email.status, email.confidence, email.last_verified_at = "invalid", 0, None
        elif event in ("replied", "human_confirmed"):
            email.status, email.confidence, email.last_verified_at = "confirmed", 98, now
            if event == "human_confirmed":
                email.provenance = "human_confirmed"
        email.verification = {**(email.verification or {}), "last_event": event, "last_event_at": now.isoformat()}
        effect = {"status": [before, email.status], "confidence": email.confidence}
    elif event in PHONE_EVENTS:
        phone = _owned(db, Phone, phone_id, company_id, "Phone")
        person_id = phone.person_id
        before = (phone.status, phone.phone_type)
        if event == "number_confirmed":
            phone.status, phone.last_verified_at = "verified", now
        elif event == "wrong_number":
            phone.status = "invalid"
        elif event == "company_switchboard":
            phone.phone_type, phone.provenance = "company_switchboard", "human_confirmed"
        elif event == "extension_confirmed":
            phone.phone_type, phone.status, phone.last_verified_at = "office_extension", "verified", now
            phone.provenance = "human_confirmed"
        effect = {"before": list(before), "after": [phone.status, phone.phone_type]}
    else:
        role = _owned(db, CompanyPerson, company_person_id, company_id, "Person")
        person_id = role.person_id
        if event == "correct_person":
            effect = _correct(role, user, employment_status="current")
            role.last_verified_at = now
        elif event == "person_left_company":
            effect = _correct(role, user, employment_status="former")
        elif event == "title_changed":
            if not (value or "").strip():
                raise BusinessRuleError("title_changed needs the new title")
            effect = _correct(role, user, job_title=value.strip()[:300])
        else:  # wrong_person
            effect = _correct(role, user, confidence=0, employment_status="unknown")
    row = ContactFeedback(event=event, company_id=company_id, person_id=person_id, company_person_id=company_person_id,
                          email_id=email_id, phone_id=phone_id, value=(value or None) and value[:320],
                          note=(note or None) and note[:500], effect=effect, user_id=user.id)
    db.add(row)
    db.commit()
    return row
