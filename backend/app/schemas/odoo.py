from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import CrmLeadType, ImportStatus, ImportType
from app.schemas.common import EntityRef, OutModel, UserBrief


class SalespersonBrief(OutModel):
    id: int
    name: str


class CrmLeadOut(OutModel):
    id: int
    odoo_lead_id: int | None
    odoo_external_id: str | None
    opportunity_name: str
    company_name: str | None
    contact_name: str | None
    email: str | None
    phone: str | None
    mobile: str | None
    salesperson_name: str | None
    salesperson: SalespersonBrief | None
    sales_team: str | None
    stage: str | None
    lead_type: CrmLeadType
    expected_revenue: Decimal | None
    probability: Decimal | None
    active: bool
    is_won: bool
    is_lost: bool
    is_open: bool
    lost_reason: str | None
    created_date: datetime | None
    updated_date: datetime | None
    last_activity: datetime | None
    company: EntityRef | None
    imported_at: datetime


class OdooContactOut(OutModel):
    id: int
    odoo_contact_id: int | None
    odoo_external_id: str | None
    contact_name: str
    is_company: bool
    parent_company: str | None
    website: str | None
    email: str | None
    phone: str | None
    mobile: str | None
    city: str | None
    country: str | None
    is_customer: bool
    salesperson_name: str | None
    salesperson: SalespersonBrief | None
    company: EntityRef | None
    imported_at: datetime


class ImportRunOut(OutModel):
    id: int
    import_type: ImportType
    status: ImportStatus
    original_filename: str
    file_type: str
    file_size: int
    row_count: int
    valid_count: int
    warning_count: int
    duplicate_count: int
    inserted_count: int
    updated_count: int
    skipped_count: int
    error_count: int
    companies_created: int
    companies_linked: int
    column_mapping: dict[str, str]
    detected_columns: list[str]
    issues: list[dict[str, Any]]
    failure_reason: str | None
    creator: UserBrief | None
    created_at: datetime
    completed_at: datetime | None


class ImportFieldOut(BaseModel):
    key: str
    label: str
    required: bool
    important: bool
    column: str | None


class ImportSampleRow(BaseModel):
    row: int
    status: str
    values: dict[str, Any]
    messages: list[str]
    company_match: dict[str, Any] | None


class ImportPreview(BaseModel):
    run: ImportRunOut
    type_label: str
    fields: list[ImportFieldOut]
    unmapped_columns: list[str]
    missing_important: list[str]
    new_records: int
    existing_records: int
    companies_matched: int
    companies_new: int
    sample_rows: list[ImportSampleRow]
    previous_import: dict[str, Any] | None


class ImportMappingUpdate(BaseModel):
    mapping: dict[str, str | None] = Field(max_length=60)
