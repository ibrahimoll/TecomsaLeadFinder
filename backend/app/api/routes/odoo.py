"""Imported Odoo records (CRM protection view) and TECOMSA salespeople."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import AdminUser, DbSession, ManagerOrAdmin, Pagination
from app.schemas.common import Page
from app.schemas.odoo import CrmLeadOut, OdooContactOut
from app.schemas.salesperson import SalespersonOut, SalespersonRow, SalespersonUpdate
from app.services import odoo_records_service, salesperson_service
from app.services.odoo_records_service import LeadState
from app.services.pagination import page_response

router = APIRouter(tags=["odoo"])


@router.get("/odoo/leads", response_model=Page[CrmLeadOut])
def list_crm_leads(
    _: ManagerOrAdmin,
    db: DbSession,
    params: Pagination,
    q: Annotated[str | None, Query(max_length=200)] = None,
    state: LeadState | None = None,
    salesperson_id: int | None = None,
    stage: Annotated[str | None, Query(max_length=200)] = None,
):
    items, total = odoo_records_service.list_leads(
        db, params, q=q, state=state, salesperson_id=salesperson_id, stage=stage
    )
    return page_response(items, total, params)


@router.get("/odoo/stages", response_model=list[str])
def list_stages(_: ManagerOrAdmin, db: DbSession):
    return odoo_records_service.lead_stages(db)


@router.get("/odoo/contacts", response_model=Page[OdooContactOut])
def list_odoo_contacts(
    _: ManagerOrAdmin,
    db: DbSession,
    params: Pagination,
    q: Annotated[str | None, Query(max_length=200)] = None,
    companies_only: bool = False,
    customers_only: bool = False,
    salesperson_id: int | None = None,
):
    items, total = odoo_records_service.list_contacts(
        db, params, q=q, companies_only=companies_only, customers_only=customers_only,
        salesperson_id=salesperson_id,
    )
    return page_response(items, total, params)


@router.get("/salespeople", response_model=list[SalespersonRow])
def list_salespeople(_: ManagerOrAdmin, db: DbSession):
    return salesperson_service.list_salespeople(db)


@router.patch("/salespeople/{salesperson_id}", response_model=SalespersonOut)
def update_salesperson(salesperson_id: int, payload: SalespersonUpdate, admin: AdminUser, db: DbSession):
    return salesperson_service.update_salesperson(db, admin, salesperson_id, payload)
