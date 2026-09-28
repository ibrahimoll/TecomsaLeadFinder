from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Campaign, Company, User
from app.models.enums import CampaignStatus
from app.services import activity_service, lusha_usage_service, permissions
from app.services.pagination import PageParams


def get_summary(db: Session, user: User) -> dict[str, Any]:
    """Only real, stored figures. No projected or fictional sales metrics."""
    total_companies = db.scalar(select(func.count(Company.id))) or 0
    my_campaigns = db.scalar(select(func.count(Campaign.id)).where(Campaign.created_by == user.id)) or 0
    draft_campaigns = (
        db.scalar(
            select(func.count(Campaign.id)).where(
                permissions.campaign_visibility_filter(user),
                Campaign.status == CampaignStatus.DRAFT,
            )
        )
        or 0
    )
    recent_companies = db.scalars(
        select(Company).order_by(Company.created_at.desc(), Company.id.desc()).limit(5)
    ).all()
    recent_activity, _ = activity_service.list_activities(
        db,
        user,
        PageParams(page=1, page_size=10),
        scope="all" if permissions.is_privileged(user) else "mine",
    )
    return {
        "total_companies": total_companies,
        "my_campaigns": my_campaigns,
        "draft_campaigns": draft_campaigns,
        "lusha_credits_used": lusha_usage_service.total_credits(db),
        "recent_companies": list(recent_companies),
        "recent_activity": recent_activity,
    }
