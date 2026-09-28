from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbSession, Pagination
from app.models.enums import CampaignStatus, Division
from app.schemas.campaign import (
    CampaignCompanyOut,
    CampaignCreate,
    CampaignDetail,
    CampaignOut,
    CampaignUpdate,
)
from app.schemas.common import Page
from app.services import campaign_service
from app.services.pagination import page_response

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


@router.get("", response_model=Page[CampaignOut])
def list_campaigns(
    user: CurrentUser,
    db: DbSession,
    params: Pagination,
    q: Annotated[str | None, Query(max_length=200)] = None,
    status: CampaignStatus | None = None,
    division: Division | None = None,
    mine: bool = False,
):
    items, total = campaign_service.list_campaigns(
        db, user, params, q=q, status=status, division=division, mine=mine
    )
    return page_response(items, total, params)


@router.post("", response_model=CampaignOut, status_code=status.HTTP_201_CREATED)
def create_campaign(payload: CampaignCreate, user: CurrentUser, db: DbSession):
    return campaign_service.create_campaign(db, user, payload)


@router.get("/{campaign_id}", response_model=CampaignDetail)
def get_campaign(campaign_id: int, user: CurrentUser, db: DbSession):
    detail = campaign_service.get_campaign_detail(db, user, campaign_id)
    base = CampaignOut.model_validate(detail.pop("campaign")).model_dump()
    return CampaignDetail.model_validate(
        {
            **base,
            **detail,
            "companies": [CampaignCompanyOut.model_validate(c) for c in detail["companies"]],
        }
    )


@router.patch("/{campaign_id}", response_model=CampaignOut)
def update_campaign(campaign_id: int, payload: CampaignUpdate, user: CurrentUser, db: DbSession):
    return campaign_service.update_campaign(db, user, campaign_id, payload)


@router.post(
    "/{campaign_id}/companies/{company_id}",
    response_model=CampaignCompanyOut,
    status_code=status.HTTP_201_CREATED,
)
def add_company_to_campaign(campaign_id: int, company_id: int, user: CurrentUser, db: DbSession):
    return campaign_service.add_company(db, user, campaign_id, company_id)
