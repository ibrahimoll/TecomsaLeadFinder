from typing import Literal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models import Campaign, LeadActivity, User
from app.models.enums import ActivityType
from app.services import permissions
from app.services.pagination import PageParams, paginate


def record(
    db: Session,
    *,
    activity_type: ActivityType,
    user_id: int | None,
    company_id: int | None = None,
    campaign_id: int | None = None,
    contact_id: int | None = None,
    notes: str | None = None,
) -> LeadActivity:
    """Add an activity to the current transaction (the caller commits)."""
    activity = LeadActivity(
        activity_type=activity_type,
        user_id=user_id,
        company_id=company_id,
        campaign_id=campaign_id,
        contact_id=contact_id,
        notes=notes,
    )
    db.add(activity)
    return activity


def list_activities(
    db: Session,
    user: User,
    params: PageParams,
    *,
    scope: Literal["mine", "all"] = "mine",
    company_id: int | None = None,
    campaign_id: int | None = None,
):
    stmt = select(LeadActivity)

    if campaign_id is not None:
        campaign = db.get(Campaign, campaign_id)
        if campaign is None or not permissions.can_view_campaign(user, campaign):
            raise NotFoundError("Campaign not found")
        stmt = stmt.where(LeadActivity.campaign_id == campaign_id)

    if company_id is not None:
        stmt = stmt.where(LeadActivity.company_id == company_id)

    if company_id is None and campaign_id is None:
        # Timeline views: agents always see their own; managers/admins may see the team.
        if scope == "mine" or not permissions.is_privileged(user):
            stmt = stmt.where(LeadActivity.user_id == user.id)

    if not permissions.is_privileged(user):
        # Never reveal activity tied to campaigns the agent cannot see.
        visible = select(Campaign.id).where(permissions.campaign_visibility_filter(user))
        stmt = stmt.where(
            or_(LeadActivity.campaign_id.is_(None), LeadActivity.campaign_id.in_(visible))
        )

    stmt = stmt.order_by(LeadActivity.created_at.desc(), LeadActivity.id.desc())
    return paginate(db, stmt, params)
