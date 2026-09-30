from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Campaign, Company, CrmLead, ImportRun, OdooContact, User
from app.models.enums import PROTECTED_STATUSES, CampaignStatus, ImportStatus, OdooMatchStatus
from app.services import activity_service, lusha_usage_service, permissions
from app.services.pagination import PageParams


def get_summary(db: Session, user: User) -> dict[str, Any]:
    """Only real, stored figures. No projected or fictional sales metrics."""

    def count(stmt) -> int:
        return db.scalar(stmt) or 0

    status_counts = dict(db.execute(select(Company.crm_status, func.count()).group_by(Company.crm_status)).all())
    recent_activity, _ = activity_service.list_activities(
        db, user, PageParams(page=1, page_size=10),
        scope="all" if permissions.is_privileged(user) else "mine",
    )
    return {
        "total_companies": sum(status_counts.values()),
        "protected_companies": sum(n for s, n in status_counts.items() if s in PROTECTED_STATUSES),
        "available_companies": status_counts.get(OdooMatchStatus.AVAILABLE, 0),
        "unchecked_companies": status_counts.get(OdooMatchStatus.NOT_CHECKED, 0),
        "odoo_crm_records": count(select(func.count(CrmLead.id))),
        "odoo_open_records": count(select(func.count(CrmLead.id)).where(
            CrmLead.active.is_(True), CrmLead.is_won.is_(False), CrmLead.lost_reason.is_(None))),
        "odoo_contacts": count(select(func.count(OdooContact.id))),
        "my_campaigns": count(select(func.count(Campaign.id)).where(Campaign.created_by == user.id)),
        "draft_campaigns": count(select(func.count(Campaign.id)).where(
            permissions.campaign_visibility_filter(user), Campaign.status == CampaignStatus.DRAFT)),
        "lusha_credits_used": lusha_usage_service.total_credits(db),
        "latest_imports": list(db.scalars(
            select(ImportRun).where(ImportRun.status != ImportStatus.PREVIEW)
            .order_by(ImportRun.created_at.desc()).limit(5)
        )) if permissions.is_privileged(user) else [],
        "recent_companies": list(db.scalars(
            select(Company).order_by(Company.created_at.desc(), Company.id.desc()).limit(6))),
        "recent_campaigns": list(db.scalars(
            select(Campaign).where(permissions.campaign_visibility_filter(user))
            .order_by(Campaign.created_at.desc()).limit(5))),
        "recent_activity": recent_activity,
    }
