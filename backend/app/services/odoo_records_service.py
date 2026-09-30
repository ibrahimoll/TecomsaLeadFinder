"""Read-only views over imported Odoo data (the CRM protection view)."""

from typing import Literal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import CrmLead, OdooContact
from app.services.pagination import PageParams, paginate

LeadState = Literal["open", "won", "lost"]


def list_leads(
    db: Session,
    params: PageParams,
    *,
    q: str | None = None,
    state: LeadState | None = None,
    salesperson_id: int | None = None,
    stage: str | None = None,
):
    stmt = select(CrmLead)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(CrmLead.opportunity_name.ilike(like), CrmLead.company_name.ilike(like),
                              CrmLead.contact_name.ilike(like), CrmLead.email.ilike(like)))
    if state == "won":
        stmt = stmt.where(CrmLead.is_won.is_(True))
    elif state == "lost":
        stmt = stmt.where(CrmLead.is_won.is_(False),
                          or_(CrmLead.active.is_(False), CrmLead.lost_reason.is_not(None)))
    elif state == "open":
        stmt = stmt.where(CrmLead.is_won.is_(False), CrmLead.active.is_(True), CrmLead.lost_reason.is_(None))
    if salesperson_id:
        stmt = stmt.where(CrmLead.salesperson_id == salesperson_id)
    if stage:
        stmt = stmt.where(CrmLead.stage == stage)
    order = (CrmLead.updated_date.desc().nulls_last(), CrmLead.id.desc())
    return paginate(db, stmt.order_by(*order), params)


def lead_stages(db: Session) -> list[str]:
    return list(db.scalars(select(CrmLead.stage).where(CrmLead.stage.is_not(None)).distinct().order_by(CrmLead.stage)))


def list_contacts(
    db: Session,
    params: PageParams,
    *,
    q: str | None = None,
    companies_only: bool = False,
    customers_only: bool = False,
    salesperson_id: int | None = None,
):
    stmt = select(OdooContact)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(OdooContact.contact_name.ilike(like), OdooContact.parent_company.ilike(like),
                              OdooContact.email.ilike(like), OdooContact.domain.ilike(like)))
    if companies_only:
        stmt = stmt.where(OdooContact.is_company.is_(True))
    if customers_only:
        stmt = stmt.where(OdooContact.is_customer.is_(True))
    if salesperson_id:
        stmt = stmt.where(OdooContact.salesperson_id == salesperson_id)
    return paginate(db, stmt.order_by(OdooContact.contact_name, OdooContact.id), params)
