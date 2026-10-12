from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DbSession, ManagerOrAdmin
from app.services import company_service, lusha

router = APIRouter(tags=["lusha"])


class SearchIn(BaseModel):
    q: str = Field(default="", max_length=200)  # typed words: "IT manager", "CFO", "marketing"; "" = everyone
    has_phone: bool = False
    page: int = Field(default=0, ge=0, le=1000)


class RevealIn(BaseModel):
    contact_id: str = Field(min_length=1, max_length=200)
    field: Literal["email", "phone"]


@router.get("/companies/{company_id}/lusha")
def company_lusha_people(company_id: int, user: CurrentUser, db: DbSession,
                         q: Annotated[str, Query(max_length=200)] = "", has_phone: bool = False,
                         page: Annotated[int, Query(ge=0, le=1000)] = 0) -> dict:
    """The cached result of this search at the company (masked; never calls Lusha)."""
    return lusha.results(db, company_service.get_company(db, company_id), q, has_phone, page)


@router.post("/companies/{company_id}/lusha/search")
def company_lusha_search(company_id: int, payload: SearchIn, user: CurrentUser, db: DbSession) -> dict:
    """Paid (per result, after the user confirmed): Lusha's people at the company for the typed words."""
    return lusha.search(db, user, company_service.get_company(db, company_id), payload.q, payload.has_phone,
                        payload.page)


@router.post("/companies/{company_id}/lusha/reveal")
def company_lusha_reveal(company_id: int, payload: RevealIn, user: CurrentUser, db: DbSession) -> dict:
    """Paid (after the user confirmed): one person's email or phone; already revealed = free, from the ledger."""
    return lusha.reveal(db, user, company_service.get_company(db, company_id), payload.contact_id, payload.field)


@router.get("/lusha/credits")
def lusha_credits(user: CurrentUser, db: DbSession) -> dict:
    return lusha.credits(db, user)


@router.get("/lusha/ledger")
def lusha_ledger(user: ManagerOrAdmin, db: DbSession) -> list[dict]:
    """Who revealed / searched what, and the credits (managers and admins)."""
    return lusha.ledger(db)
