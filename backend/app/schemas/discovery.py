from datetime import datetime
from typing import Any

from pydantic import Field

from app.models.enums import DiscoveryState, DiscoveryStatus, OdooMatchStatus
from app.schemas.common import InModel, OutModel, UserBrief


class DiscoveryRunCreate(InModel):
    country: str = Field(default="LB", min_length=2, max_length=2)
    city: str | None = Field(default=None, max_length=50)
    industry: str | None = Field(default=None, max_length=50)
    custom_query: str | None = Field(default=None, max_length=200)
    requested_count: int = Field(default=100, ge=1, le=1000)


class DiscoveryRunOut(OutModel):
    id: int
    country: str
    city: str | None
    industry: str | None
    custom_query: str | None
    query_label: str
    requested_count: int
    sources: list[str]
    source_version: str | None
    status: DiscoveryStatus
    progress: list[dict[str, Any]]
    started_at: datetime | None
    finished_at: datetime | None
    source_match_count: int
    raw_results_count: int
    duplicate_count: int
    existing_company_count: int
    odoo_protected_count: int
    new_company_count: int
    error_count: int
    errors: list[str]
    summary: str | None
    creator: UserBrief | None
    created_at: datetime


class DiscoveryCompanyBrief(OutModel):
    id: int
    name: str
    odoo_status: OdooMatchStatus


class DiscoveryResultOut(OutModel):
    id: int
    position: int
    source: str
    external_id: str | None
    name: str
    category: str | None
    address: str | None
    city: str | None
    country: str | None
    phone: str | None
    website: str | None
    email: str | None
    latitude: float | None
    longitude: float | None
    state: DiscoveryState
    reason: str | None
    match_reason: str | None
    duplicate_of_id: int | None
    company: DiscoveryCompanyBrief | None


class DiscoveryResultsPage(OutModel):
    items: list[DiscoveryResultOut]
    total: int
    page: int
    page_size: int
    counts: dict[str, int]


class DiscoveryDeleteResult(OutModel):
    id: int
    with_data: bool
    companies_removed: int
    companies_kept: int


class CompanySourceOut(OutModel):
    source: str
    source_label: str
    external_id: str
    category: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    first_seen_run_id: int | None
