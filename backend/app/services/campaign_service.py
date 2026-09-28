from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError, PermissionDeniedError
from app.models import Campaign, CampaignCompany, User
from app.models.enums import ActivityType, CampaignCompanyStatus, CampaignStatus, Division
from app.schemas.campaign import CampaignCreate, CampaignUpdate
from app.services import (
    activity_service,
    audit_service,
    company_service,
    lusha_usage_service,
    permissions,
)
from app.services.audit_service import AuditAction
from app.services.pagination import PageParams, paginate

# Phase 0 has no execution engine, so only these manual transitions are allowed.
# RUNNING / COMPLETED / FAILED will be set by the lead-generation pipeline in later phases.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    CampaignStatus.DRAFT: {CampaignStatus.READY, CampaignStatus.CANCELLED},
    CampaignStatus.READY: {CampaignStatus.DRAFT, CampaignStatus.CANCELLED},
}
OPEN_STATUSES = (CampaignStatus.DRAFT, CampaignStatus.READY)


def _attach_company_counts(db: Session, campaigns: list[Campaign]) -> None:
    if not campaigns:
        return
    rows = db.execute(
        select(CampaignCompany.campaign_id, func.count(CampaignCompany.id))
        .where(
            CampaignCompany.campaign_id.in_([c.id for c in campaigns]),
            CampaignCompany.status != CampaignCompanyStatus.REMOVED,
        )
        .group_by(CampaignCompany.campaign_id)
    ).all()
    counts = dict(rows)
    for campaign in campaigns:
        campaign.company_count = counts.get(campaign.id, 0)


def list_campaigns(
    db: Session,
    user: User,
    params: PageParams,
    *,
    q: str | None = None,
    status: CampaignStatus | None = None,
    division: Division | None = None,
    mine: bool = False,
) -> tuple[list[Campaign], int]:
    stmt = select(Campaign).where(permissions.campaign_visibility_filter(user))
    if mine:
        stmt = stmt.where(Campaign.created_by == user.id)
    if q:
        stmt = stmt.where(Campaign.name.ilike(f"%{q.strip()}%"))
    if status:
        stmt = stmt.where(Campaign.status == status)
    if division:
        stmt = stmt.where(Campaign.tecomsa_division == division)
    stmt = stmt.order_by(Campaign.created_at.desc(), Campaign.id.desc())
    items, total = paginate(db, stmt, params)
    _attach_company_counts(db, items)
    return items, total


def get_campaign(db: Session, user: User, campaign_id: int) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    # Invisible campaigns are reported as missing so their existence is not disclosed.
    if campaign is None or not permissions.can_view_campaign(user, campaign):
        raise NotFoundError("Campaign not found")
    return campaign


def create_campaign(db: Session, actor: User, data: CampaignCreate) -> Campaign:
    values = data.model_dump()
    values["target_roles"] = values["target_roles"] or []
    campaign = Campaign(**values, created_by=actor.id, status=CampaignStatus.DRAFT)
    db.add(campaign)
    db.flush()
    activity_service.record(
        db,
        activity_type=ActivityType.CAMPAIGN_CREATED,
        user_id=actor.id,
        campaign_id=campaign.id,
        notes=f"Campaign '{campaign.name}' created as draft",
    )
    audit_service.record(
        db,
        action=AuditAction.CAMPAIGN_CREATED,
        user_id=actor.id,
        entity_type="campaign",
        entity_id=campaign.id,
        metadata={
            "name": campaign.name,
            "division": campaign.tecomsa_division,
            "country": campaign.country,
            "target_company_count": campaign.target_company_count,
        },
    )
    db.commit()
    db.refresh(campaign)
    campaign.company_count = 0
    return campaign


def update_campaign(db: Session, actor: User, campaign_id: int, data: CampaignUpdate) -> Campaign:
    campaign = get_campaign(db, actor, campaign_id)
    if not permissions.can_manage_campaign(actor, campaign):
        raise PermissionDeniedError("You cannot edit this campaign")

    changes = data.model_dump(exclude_unset=True)
    new_status = changes.pop("status", None)
    if "target_roles" in changes and changes["target_roles"] is None:
        changes["target_roles"] = []

    if changes and campaign.status != CampaignStatus.DRAFT:
        raise ConflictError("Only draft campaigns can be edited")

    merged_min = changes.get("company_size_min", campaign.company_size_min)
    merged_max = changes.get("company_size_max", campaign.company_size_max)
    if merged_min is not None and merged_max is not None and merged_min > merged_max:
        raise BusinessRuleError("Minimum company size cannot exceed maximum company size")

    diff: dict[str, dict] = {}
    for field, value in changes.items():
        old = getattr(campaign, field)
        if old != value:
            diff[field] = {"from": old, "to": value}
            setattr(campaign, field, value)

    if new_status is not None and new_status != campaign.status:
        if new_status not in ALLOWED_TRANSITIONS.get(campaign.status, set()):
            raise BusinessRuleError(
                f"Status cannot change from {campaign.status} to {new_status} in this phase"
            )
        diff["status"] = {"from": campaign.status, "to": new_status}
        campaign.status = new_status

    if diff:
        audit_service.record(
            db,
            action=AuditAction.CAMPAIGN_UPDATED,
            user_id=actor.id,
            entity_type="campaign",
            entity_id=campaign.id,
            metadata={"changes": diff},
        )
        db.commit()
        db.refresh(campaign)
    _attach_company_counts(db, [campaign])
    return campaign


def add_company(db: Session, actor: User, campaign_id: int, company_id: int) -> CampaignCompany:
    campaign = get_campaign(db, actor, campaign_id)
    if not permissions.can_manage_campaign(actor, campaign):
        raise PermissionDeniedError("You cannot modify this campaign")
    if campaign.status not in OPEN_STATUSES:
        raise ConflictError(f"Companies cannot be added to a {campaign.status} campaign")
    company = company_service.get_company(db, company_id)

    link = db.scalar(
        select(CampaignCompany).where(
            CampaignCompany.campaign_id == campaign.id, CampaignCompany.company_id == company.id
        )
    )
    if link is not None and link.status != CampaignCompanyStatus.REMOVED:
        raise ConflictError("This company is already in the campaign")
    if link is None:
        link = CampaignCompany(campaign_id=campaign.id, company_id=company.id, added_by=actor.id)
        db.add(link)
    else:
        link.status = CampaignCompanyStatus.ADDED
        link.added_by = actor.id
    db.flush()

    activity_service.record(
        db,
        activity_type=ActivityType.COMPANY_ADDED_TO_CAMPAIGN,
        user_id=actor.id,
        company_id=company.id,
        campaign_id=campaign.id,
        notes=f"'{company.name}' added to campaign '{campaign.name}'",
    )
    audit_service.record(
        db,
        action=AuditAction.CAMPAIGN_COMPANY_ADDED,
        user_id=actor.id,
        entity_type="campaign",
        entity_id=campaign.id,
        metadata={"company_id": company.id, "campaign_company_id": link.id},
    )
    db.commit()
    db.refresh(link)
    return link


def get_campaign_detail(db: Session, user: User, campaign_id: int) -> dict[str, Any]:
    campaign = get_campaign(db, user, campaign_id)
    _attach_company_counts(db, [campaign])
    links = db.scalars(
        select(CampaignCompany)
        .where(
            CampaignCompany.campaign_id == campaign.id,
            CampaignCompany.status != CampaignCompanyStatus.REMOVED,
        )
        .order_by(CampaignCompany.created_at.desc(), CampaignCompany.id.desc())
    ).all()
    return {
        "campaign": campaign,
        "companies": list(links),
        "lusha_credits_used": lusha_usage_service.total_credits(db, campaign_id=campaign.id),
        "can_edit": permissions.can_manage_campaign(user, campaign),
    }
