from typing import Any, Literal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.models import Campaign, CampaignCompany, Company, User
from app.models.enums import PROTECTED_STATUSES, ActivityType, CompanySource, OdooMatchStatus
from app.schemas.company import CompanyCreate, CompanyUpdate
from app.services import (
    activity_service,
    audit_service,
    lusha_usage_service,
    matching_service,
    permissions,
    relationship_service,
)
from app.services.audit_service import AuditAction
from app.services.matching_service import MatchSignals
from app.services.normalization import (
    email_domain,
    normalize_company_name,
    normalize_domain,
    normalize_phone,
    normalize_website,
)
from app.services.pagination import PageParams, paginate

_PLAIN_FIELDS = ("country", "city", "address", "industry", "main_email", "company_size", "description")
# Changing any of these can change which Odoo records match the company.
_IDENTITY_FIELDS = {"name", "website", "main_phone", "main_email", "city", "country"}

SortKey = Literal["created", "name", "status", "updated"]
_SORTS = {
    "created": (Company.created_at.desc(), Company.id.desc()),
    "updated": (Company.updated_at.desc(), Company.id.desc()),
    "name": (Company.normalized_name.asc(), Company.id.asc()),
    "status": (Company.crm_status.asc(), Company.normalized_name.asc()),
}


def list_companies(
    db: Session,
    params: PageParams,
    *,
    q: str | None = None,
    country: str | None = None,
    industry: str | None = None,
    crm_status: OdooMatchStatus | None = None,
    protected: bool | None = None,
    source: CompanySource | None = None,
    salesperson_id: int | None = None,
    sort: SortKey = "created",
) -> tuple[list[Company], int]:
    stmt = select(Company)
    if q:
        term = q.strip()
        like = f"%{term}%"
        stmt = stmt.where(
            or_(
                Company.name.ilike(like),
                Company.normalized_name.ilike(f"%{normalize_company_name(term)}%"),
                Company.domain.ilike(like),
                Company.city.ilike(like),
            )
        )
    if country:
        stmt = stmt.where(Company.country == country)
    if industry:
        stmt = stmt.where(Company.industry == industry)
    if crm_status:
        stmt = stmt.where(Company.crm_status == crm_status)
    if protected is not None:
        condition = Company.crm_status.in_(list(PROTECTED_STATUSES))
        stmt = stmt.where(condition if protected else ~condition)
    if source:
        stmt = stmt.where(Company.source == source)
    if salesperson_id:
        stmt = stmt.where(Company.salesperson_id == salesperson_id)
    return paginate(db, stmt.order_by(*_SORTS[sort]), params)


def get_company(db: Session, company_id: int) -> Company:
    company = db.get(Company, company_id)
    if company is None:
        raise NotFoundError("Company not found")
    return company


def _signals(data: CompanyCreate | Company) -> MatchSignals:
    return MatchSignals(name=data.name, website=data.website, email=data.main_email,
                        phone=data.main_phone, city=data.city, country=data.country)


def find_duplicates(db: Session, signals: MatchSignals, exclude_id: int | None = None) -> list[dict[str, Any]]:
    return [
        {"company": m.company, "score": round(m.score, 2), "reason": m.reason}
        for m in matching_service.find_matches(db, signals, exclude_id=exclude_id)
    ]


def create_company(db: Session, actor: User, data: CompanyCreate) -> Company:
    company = Company(
        name=data.name,
        normalized_name=normalize_company_name(data.name),
        website=normalize_website(data.website),
        domain=normalize_domain(data.website),
        main_phone=data.main_phone,
        main_phone_normalized=normalize_phone(data.main_phone, data.country),
        source=CompanySource.MANUAL,
        created_by=actor.id,
        **{f: getattr(data, f) for f in _PLAIN_FIELDS},
    )
    if company.main_email:
        company.main_email = company.main_email.lower()
        company.email_domain = email_domain(company.main_email)
    db.add(company)
    db.flush()

    # Checked against imported Odoo data; NOT_CHECKED when no Odoo import exists yet.
    relationship_service.refresh_company(db, company)
    activity_service.record(
        db,
        activity_type=ActivityType.COMPANY_CREATED,
        user_id=actor.id,
        company_id=company.id,
        notes=f"Company '{company.name}' added manually",
    )
    audit_service.record(
        db,
        action=AuditAction.COMPANY_CREATED,
        user_id=actor.id,
        entity_type="company",
        entity_id=company.id,
        metadata={"name": company.name, "domain": company.domain, "source": "MANUAL",
                  "crm_status": company.crm_status},
    )
    db.commit()
    db.refresh(company)
    return company


def update_company(db: Session, actor: User, company_id: int, data: CompanyUpdate) -> Company:
    company = get_company(db, company_id)
    if not permissions.can_edit_company(actor, company):
        raise PermissionDeniedError("You can only edit companies you created")

    changes = data.model_dump(exclude_unset=True)
    if "main_email" in changes and changes["main_email"]:
        changes["main_email"] = str(changes["main_email"]).lower()

    new_values: dict[str, Any] = {}
    if "name" in changes:
        new_values["name"] = changes["name"]
        new_values["normalized_name"] = normalize_company_name(changes["name"])
    if "website" in changes:
        new_values["website"] = normalize_website(changes["website"])
        new_values["domain"] = normalize_domain(changes["website"])
    if "main_phone" in changes or "country" in changes:
        phone = changes.get("main_phone", company.main_phone)
        new_values["main_phone"] = phone
        new_values["main_phone_normalized"] = normalize_phone(phone, changes.get("country", company.country))
    if "main_email" in changes:
        new_values["email_domain"] = email_domain(changes["main_email"])
    for field in _PLAIN_FIELDS:
        if field in changes:
            new_values[field] = changes[field]

    diff: dict[str, dict] = {}
    for field, value in new_values.items():
        old = getattr(company, field)
        if old != value:
            diff[field] = {"from": old, "to": value}
            setattr(company, field, value)

    if diff:
        if _IDENTITY_FIELDS & diff.keys():
            relationship_service.refresh_company(db, company)
        audit_service.record(
            db,
            action=AuditAction.COMPANY_UPDATED,
            user_id=actor.id,
            entity_type="company",
            entity_id=company.id,
            metadata={"changes": diff},
        )
        db.commit()
        db.refresh(company)
    return company


def add_note(db: Session, actor: User, company_id: int, notes: str) -> None:
    company = get_company(db, company_id)
    activity = activity_service.record(
        db,
        activity_type=ActivityType.NOTE_ADDED,
        user_id=actor.id,
        company_id=company.id,
        notes=notes,
    )
    db.flush()
    audit_service.record(
        db,
        action=AuditAction.COMPANY_NOTE_ADDED,
        user_id=actor.id,
        entity_type="company",
        entity_id=company.id,
        metadata={"activity_id": activity.id},
    )
    db.commit()


def get_company_detail(db: Session, user: User, company_id: int) -> dict[str, Any]:
    company = get_company(db, company_id)

    links = db.scalars(
        select(CampaignCompany)
        .join(Campaign, Campaign.id == CampaignCompany.campaign_id)
        .where(CampaignCompany.company_id == company.id)
        .where(permissions.campaign_visibility_filter(user))
        .order_by(CampaignCompany.created_at.desc())
    ).all()
    evidence = relationship_service.evidence_for(db, company)
    activity_dates = [d for lead in evidence.leads for d in (lead.last_activity, lead.updated_date) if d]

    return {
        "company": company,
        "contacts": company.contacts,
        "campaigns": [
            {
                "campaign_id": link.campaign.id,
                "campaign_name": link.campaign.name,
                "tecomsa_division": link.campaign.tecomsa_division,
                "campaign_status": link.campaign.status,
                "status": link.status,
                "qualification_status": link.qualification_status,
                "added_at": link.created_at,
            }
            for link in links
        ],
        "odoo_match": company.odoo_matches[0] if company.odoo_matches else None,
        "relationship": {
            "crm_records": evidence.leads,
            "odoo_contacts": evidence.contacts,
            "last_interaction": max(activity_dates) if activity_dates else None,
        },
        "possible_duplicates": find_duplicates(db, _signals(company), exclude_id=company.id),
        "lusha_credits_used": lusha_usage_service.total_credits(db, company_id=company.id),
        "can_edit": permissions.can_edit_company(user, company),
    }
