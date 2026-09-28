from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbSession, Pagination
from app.schemas.common import Page
from app.schemas.contact import ContactCreate, ContactOut
from app.services import contact_service
from app.services.pagination import page_response

router = APIRouter(prefix="/contacts", tags=["contacts"])


@router.get("", response_model=Page[ContactOut])
def list_contacts(
    _: CurrentUser,
    db: DbSession,
    params: Pagination,
    company_id: int | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
):
    items, total = contact_service.list_contacts(db, params, company_id=company_id, q=q)
    return page_response(items, total, params)


@router.post("", response_model=ContactOut, status_code=status.HTTP_201_CREATED)
def create_contact(payload: ContactCreate, user: CurrentUser, db: DbSession):
    return contact_service.create_contact(db, user, payload)
