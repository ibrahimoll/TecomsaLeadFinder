from datetime import datetime

from pydantic import BaseModel

from app.models.enums import CampaignStatus, Division, ImportStatus, ImportType
from app.schemas.activity import ActivityOut
from app.schemas.common import OutModel
from app.schemas.company import CompanyOut


class ImportSummary(OutModel):
    id: int
    import_type: ImportType
    status: ImportStatus
    original_filename: str
    row_count: int
    inserted_count: int
    updated_count: int
    created_at: datetime


class CampaignSummary(OutModel):
    id: int
    name: str
    tecomsa_division: Division
    status: CampaignStatus
    target_company_count: int
    created_at: datetime


class DashboardSummary(BaseModel):
    total_companies: int
    protected_companies: int
    available_companies: int
    unchecked_companies: int
    odoo_crm_records: int
    odoo_open_records: int
    odoo_contacts: int
    my_campaigns: int
    draft_campaigns: int
    lusha_credits_used: int
    latest_imports: list[ImportSummary]
    recent_companies: list[CompanyOut]
    recent_campaigns: list[CampaignSummary]
    recent_activity: list[ActivityOut]


class IntegrationStatus(BaseModel):
    name: str
    status: str  # CONFIGURED | NOT_CONFIGURED | DISABLED | ERROR
    detail: str


class SystemStatus(BaseModel):
    version: str
    environment: str
    managers_can_import: bool
    last_odoo_import_at: datetime | None
    integrations: list[IntegrationStatus]
