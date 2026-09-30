from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbSession, Pagination
from app.models.enums import CompanySource, OdooMatchStatus
from app.schemas.common import Page
from app.schemas.company import (
    CompanyCreate,
    CompanyDetail,
    CompanyNoteCreate,
    CompanyOut,
    CompanyUpdate,
    DuplicateCandidate,
)
from app.services import company_service
from app.services.company_service import SortKey
from app.services.matching_service import MatchSignals
from app.services.pagination import page_response

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("", response_model=Page[CompanyOut])
def list_companies(
    _: CurrentUser,
    db: DbSession,
    params: Pagination,
    q: Annotated[str | None, Query(max_length=200)] = None,
    country: Annotated[str | None, Query(max_length=100)] = None,
    industry: Annotated[str | None, Query(max_length=150)] = None,
    crm_status: OdooMatchStatus | None = None,
    protected: bool | None = None,
    source: CompanySource | None = None,
    salesperson_id: int | None = None,
    sort: SortKey = "created",
):
    items, total = company_service.list_companies(
        db, params, q=q, country=country, industry=industry, crm_status=crm_status,
        protected=protected, source=source, salesperson_id=salesperson_id, sort=sort,
    )
    return page_response(items, total, params)


@router.get("/duplicates", response_model=list[DuplicateCandidate])
def check_duplicates(
    _: CurrentUser,
    db: DbSession,
    name: Annotated[str | None, Query(max_length=255)] = None,
    website: Annotated[str | None, Query(max_length=500)] = None,
    email: Annotated[str | None, Query(max_length=320)] = None,
    phone: Annotated[str | None, Query(max_length=50)] = None,
    city: Annotated[str | None, Query(max_length=100)] = None,
    country: Annotated[str | None, Query(max_length=100)] = None,
    exclude_id: int | None = None,
):
    """Existing companies that may be the same organisation as the one being entered."""
    signals = MatchSignals(name=name, website=website, email=email, phone=phone, city=city, country=country)
    return company_service.find_duplicates(db, signals, exclude_id=exclude_id)


@router.post("", response_model=CompanyOut, status_code=status.HTTP_201_CREATED)
def create_company(payload: CompanyCreate, user: CurrentUser, db: DbSession):
    return company_service.create_company(db, user, payload)


@router.get("/{company_id}", response_model=CompanyDetail)
def get_company(company_id: int, user: CurrentUser, db: DbSession):
    detail = company_service.get_company_detail(db, user, company_id)
    base = CompanyOut.model_validate(detail.pop("company")).model_dump()
    return CompanyDetail.model_validate({**base, **detail})


@router.patch("/{company_id}", response_model=CompanyOut)
def update_company(company_id: int, payload: CompanyUpdate, user: CurrentUser, db: DbSession):
    return company_service.update_company(db, user, company_id, payload)


@router.post("/{company_id}/notes", status_code=status.HTTP_204_NO_CONTENT)
def add_note(company_id: int, payload: CompanyNoteCreate, user: CurrentUser, db: DbSession) -> None:
    company_service.add_note(db, user, company_id, payload.notes)
