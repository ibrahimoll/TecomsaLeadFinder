from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Contact, User
from app.models.enums import ActivityType, ContactSource
from app.schemas.contact import ContactCreate
from app.services import activity_service, audit_service, company_service
from app.services.audit_service import AuditAction
from app.services.pagination import PageParams, paginate


def list_contacts(
    db: Session, params: PageParams, *, company_id: int | None = None, q: str | None = None
) -> tuple[list[Contact], int]:
    stmt = select(Contact)
    if company_id is not None:
        stmt = stmt.where(Contact.company_id == company_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Contact.first_name.ilike(like),
                Contact.last_name.ilike(like),
                Contact.job_title.ilike(like),
                Contact.business_email.ilike(like),
            )
        )
    return paginate(db, stmt.order_by(Contact.created_at.desc(), Contact.id.desc()), params)


def create_contact(db: Session, actor: User, data: ContactCreate) -> Contact:
    """Create a manually entered contact. Contacts are never generated automatically."""
    company = company_service.get_company(db, data.company_id)
    contact = Contact(
        **data.model_dump(exclude={"business_email"}),
        business_email=str(data.business_email).lower() if data.business_email else None,
        source=ContactSource.MANUAL,
        created_by=actor.id,
    )
    db.add(contact)
    db.flush()
    activity_service.record(
        db,
        activity_type=ActivityType.CONTACT_ADDED,
        user_id=actor.id,
        company_id=company.id,
        contact_id=contact.id,
        notes=f"Contact '{contact.full_name}' added manually",
    )
    audit_service.record(
        db,
        action=AuditAction.CONTACT_CREATED,
        user_id=actor.id,
        entity_type="contact",
        entity_id=contact.id,
        metadata={"company_id": company.id, "source": ContactSource.MANUAL.value},
    )
    db.commit()
    db.refresh(contact)
    return contact
