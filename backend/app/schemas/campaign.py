from datetime import datetime

from pydantic import Field, field_validator, model_validator

from app.models.enums import CampaignCompanyStatus, CampaignStatus, Division, OdooMatchStatus
from app.schemas.common import InModel, OutModel, UserBrief, require_value

_ROLE_MAX = 100
_ROLES_MAX_ITEMS = 25


def _clean_roles(roles: list[str] | None) -> list[str] | None:
    if roles is None:
        return None
    cleaned: list[str] = []
    for role in roles:
        role = role.strip()
        if not role:
            continue
        if len(role) > _ROLE_MAX:
            raise ValueError(f"Target role names must be at most {_ROLE_MAX} characters")
        if role.lower() not in {r.lower() for r in cleaned}:
            cleaned.append(role)
    return cleaned


class _CampaignFields(InModel):
    region: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=100)
    industry: str | None = Field(default=None, max_length=150)
    company_size_min: int | None = Field(default=None, ge=1, le=1_000_000)
    company_size_max: int | None = Field(default=None, ge=1, le=1_000_000)
    target_roles: list[str] | None = Field(default=None, max_length=_ROLES_MAX_ITEMS)
    max_lusha_credit_budget: int | None = Field(default=None, ge=0, le=1_000_000)
    additional_instructions: str | None = Field(default=None, max_length=5000)

    @field_validator("target_roles")
    @classmethod
    def _roles(cls, v: list[str] | None) -> list[str] | None:
        return _clean_roles(v)

    @model_validator(mode="after")
    def _size_range(self):
        if (
            self.company_size_min is not None
            and self.company_size_max is not None
            and self.company_size_min > self.company_size_max
        ):
            raise ValueError("Minimum company size cannot exceed maximum company size")
        return self


class CampaignCreate(_CampaignFields):
    name: str = Field(min_length=1, max_length=200)
    tecomsa_division: Division
    country: str = Field(min_length=1, max_length=100)
    target_company_count: int = Field(ge=1, le=10_000)


class CampaignUpdate(_CampaignFields):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    tecomsa_division: Division | None = None
    country: str | None = Field(default=None, min_length=1, max_length=100)
    target_company_count: int | None = Field(default=None, ge=1, le=10_000)
    status: CampaignStatus | None = None

    @field_validator("name", "tecomsa_division", "country", "target_company_count", "status")
    @classmethod
    def _not_null(cls, v, info):
        return require_value(v, info.field_name)


class CampaignOut(OutModel):
    id: int
    name: str
    tecomsa_division: Division
    country: str
    region: str | None
    city: str | None
    industry: str | None
    company_size_min: int | None
    company_size_max: int | None
    target_roles: list[str]
    target_company_count: int
    max_lusha_credit_budget: int | None
    additional_instructions: str | None
    status: CampaignStatus
    creator: UserBrief
    company_count: int = 0
    created_at: datetime
    updated_at: datetime


class CampaignCompanyCompany(OutModel):
    id: int
    name: str
    country: str | None
    industry: str | None
    domain: str | None
    odoo_status: OdooMatchStatus


class CampaignCompanyOut(OutModel):
    id: int
    campaign_id: int
    company: CampaignCompanyCompany
    status: CampaignCompanyStatus
    qualification_status: str
    created_at: datetime


class CampaignDetail(CampaignOut):
    companies: list[CampaignCompanyOut]
    lusha_credits_used: int
    can_edit: bool
