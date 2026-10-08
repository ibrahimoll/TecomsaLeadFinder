from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.enums import CampaignCompanyStatus, CampaignStatus, CompanySource, Division, OdooMatchStatus
from app.schemas.common import InModel, OutModel, UserBrief, require_value, validate_phone
from app.schemas.contact import ContactOut
from app.schemas.discovery import CompanySourceOut
from app.schemas.odoo import CrmLeadOut, OdooContactOut, SalespersonBrief
from app.services.normalization import normalize_domain

CompanySize = Literal["1-10", "11-50", "51-200", "201-500", "501-1000", "1001-5000", "5000+"]


class _CompanyFields(InModel):
    website: str | None = Field(default=None, max_length=500)
    country: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=100)
    address: str | None = Field(default=None, max_length=500)
    industry: str | None = Field(default=None, max_length=150)
    main_phone: str | None = Field(default=None, max_length=50)
    main_email: EmailStr | None = Field(default=None, max_length=320)
    company_size: CompanySize | None = None
    description: str | None = Field(default=None, max_length=5000)

    @field_validator("website")
    @classmethod
    def _website(cls, v: str | None) -> str | None:
        if v is not None and normalize_domain(v) is None:
            raise ValueError("Website must be a valid domain or URL, e.g. example.com")
        return v

    @field_validator("main_phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        return validate_phone(v)


class CompanyCreate(_CompanyFields):
    name: str = Field(min_length=1, max_length=255)


class CompanyUpdate(_CompanyFields):
    name: str | None = Field(default=None, min_length=1, max_length=255)

    @field_validator("name")
    @classmethod
    def _name_required(cls, v: str | None) -> str:
        return require_value(v, "name")


class CompanyNoteCreate(InModel):
    notes: str = Field(min_length=1, max_length=5000)


class CompanyOut(OutModel):
    id: int
    name: str
    normalized_name: str
    website: str | None
    domain: str | None
    country: str | None
    city: str | None
    address: str | None
    industry: str | None
    main_phone: str | None
    main_phone_normalized: str | None
    main_email: str | None
    company_size: str | None
    description: str | None
    source: CompanySource | str
    source_label: str
    odoo_status: OdooMatchStatus
    crm_status_reason: str | None
    crm_checked_at: datetime | None
    is_protected: bool
    salesperson: SalespersonBrief | None
    creator: UserBrief | None
    created_at: datetime
    updated_at: datetime


class OdooMatchOut(OutModel):
    match_status: OdooMatchStatus
    odoo_partner_id: int | None
    odoo_lead_id: int | None
    match_confidence: Decimal | None
    match_reason: str | None
    checked_at: datetime | None
    created_at: datetime


class CompanyCampaignLink(OutModel):
    campaign_id: int
    campaign_name: str
    tecomsa_division: Division
    campaign_status: CampaignStatus
    status: CampaignCompanyStatus
    qualification_status: str
    added_at: datetime


class CompanyBrief(OutModel):
    id: int
    name: str
    domain: str | None
    city: str | None
    country: str | None
    source_label: str
    odoo_status: OdooMatchStatus


class DuplicateCandidate(BaseModel):
    company: CompanyBrief
    score: float
    reason: str


class Relationship(BaseModel):
    crm_records: list[CrmLeadOut]
    odoo_contacts: list[OdooContactOut]
    last_interaction: datetime | None


class CompanyDetail(CompanyOut):
    contacts: list[ContactOut]
    campaigns: list[CompanyCampaignLink]
    odoo_match: OdooMatchOut | None
    relationship: Relationship
    possible_duplicates: list[DuplicateCandidate]
    sources: list[CompanySourceOut]
    lusha_credits_used: int
    can_edit: bool
