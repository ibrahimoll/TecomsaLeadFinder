from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models import Company, CrmLead, OdooContact, Salesperson, User
from app.schemas.salesperson import SalespersonUpdate
from app.services import audit_service
from app.services.audit_service import AuditAction
from app.services.normalization import name_key


class SalespersonResolver:
    """Finds or creates salespeople by name during an import (cached per import)."""

    def __init__(self, db: Session):
        self.db = db
        self._cache: dict[str, Salesperson] = {}

    def resolve(self, name: str | None) -> Salesperson | None:
        key = name_key(name)
        if key is None:
            return None
        if key not in self._cache:
            person = self.db.scalar(select(Salesperson).where(Salesperson.name_key == key))
            if person is None:
                person = Salesperson(name=" ".join(name.split()), name_key=key)
                self.db.add(person)
                self.db.flush()
            self._cache[key] = person
        return self._cache[key]


def list_salespeople(db: Session) -> list[dict]:
    """All salespeople with how many Odoo records and companies they own."""
    people = db.scalars(select(Salesperson).order_by(Salesperson.name)).all()

    def counts(column) -> dict[int, int]:
        return dict(db.execute(select(column, func.count()).where(column.is_not(None)).group_by(column)).all())

    leads, open_leads = counts(CrmLead.salesperson_id), dict(
        db.execute(
            select(CrmLead.salesperson_id, func.count())
            .where(CrmLead.salesperson_id.is_not(None), CrmLead.active.is_(True),
                   CrmLead.is_won.is_(False), CrmLead.lost_reason.is_(None))
            .group_by(CrmLead.salesperson_id)
        ).all()
    )
    contacts, companies = counts(OdooContact.salesperson_id), counts(Company.salesperson_id)
    return [
        {
            "salesperson": p,
            "crm_records": leads.get(p.id, 0),
            "open_records": open_leads.get(p.id, 0),
            "odoo_contacts": contacts.get(p.id, 0),
            "companies": companies.get(p.id, 0),
        }
        for p in people
    ]


def update_salesperson(db: Session, actor: User, salesperson_id: int, data: SalespersonUpdate) -> Salesperson:
    person = db.get(Salesperson, salesperson_id)
    if person is None:
        raise NotFoundError("Salesperson not found")
    changes = data.model_dump(exclude_unset=True)
    if changes.get("user_id") is not None:
        if db.get(User, changes["user_id"]) is None:
            raise NotFoundError("User not found")
        taken = db.scalar(
            select(Salesperson.id).where(Salesperson.user_id == changes["user_id"], Salesperson.id != person.id)
        )
        if taken:
            raise ConflictError("That user is already linked to another salesperson")
    diff = {}
    for field, value in changes.items():
        if getattr(person, field) != value:
            diff[field] = {"from": getattr(person, field), "to": value}
            setattr(person, field, value)
    if diff:
        audit_service.record(db, action=AuditAction.SALESPERSON_UPDATED, user_id=actor.id,
                             entity_type="salesperson", entity_id=person.id, metadata={"changes": diff})
        db.commit()
        db.refresh(person)
    return person
