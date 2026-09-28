"""Provider-neutral result shapes the Odoo integration will return (Phase 1)."""

from pydantic import BaseModel, Field

from app.models.enums import OdooMatchStatus


class OdooCompanyQuery(BaseModel):
    name: str
    normalized_name: str
    domain: str | None = None
    main_phone_normalized: str | None = None
    main_email: str | None = None
    country: str | None = None


class OdooCompanyCheckResult(BaseModel):
    """Maps onto one `odoo_matches` row."""

    match_status: OdooMatchStatus
    odoo_partner_id: int | None = None
    odoo_lead_id: int | None = None
    match_confidence: float | None = Field(default=None, ge=0, le=1)
    match_reason: str | None = None


class OdooContactResult(BaseModel):
    odoo_partner_id: int
    name: str
    email: str | None = None
    phone: str | None = None
    parent_partner_id: int | None = None


class OdooOpportunityResult(BaseModel):
    odoo_lead_id: int
    name: str
    stage: str | None = None
    salesperson_odoo_user_id: int | None = None
    active: bool = True
