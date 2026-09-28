from typing import Literal

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession, Pagination
from app.schemas.activity import ActivityOut
from app.schemas.common import Page
from app.services import activity_service
from app.services.pagination import page_response

router = APIRouter(prefix="/activities", tags=["activities"])


@router.get("", response_model=Page[ActivityOut])
def list_activities(
    user: CurrentUser,
    db: DbSession,
    params: Pagination,
    scope: Literal["mine", "all"] = "mine",
    company_id: int | None = None,
    campaign_id: int | None = None,
):
    items, total = activity_service.list_activities(
        db, user, params, scope=scope, company_id=company_id, campaign_id=campaign_id
    )
    return page_response(items, total, params)
