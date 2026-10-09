from datetime import datetime
from typing import Any

from pydantic import Field

from app.models.enums import LeadSearchStatus, SearchSolution
from app.models.search import MAX_REQUESTED_COUNT
from app.schemas.common import InModel, OutModel
from app.schemas.company import CompanyOut


class LeadSearchCreate(InModel):
    country: str = Field(min_length=1, max_length=100)
    region: str | None = Field(default=None, max_length=120)
    city: str | None = Field(default=None, max_length=120)
    industry: str | None = Field(default=None, max_length=200)
    solution: SearchSolution = SearchSolution.ANY
    requested_count: int = Field(default=50, ge=1, le=MAX_REQUESTED_COUNT)


class LeadSearchOut(OutModel):
    id: int
    user_id: int
    country: str
    region: str | None
    city: str | None
    industry: str | None
    solution: SearchSolution
    requested_count: int
    status: LeadSearchStatus  # discovery: final once the companies are found
    # Research of the companies found (search_service.research_status): running / completed / None.
    enrichment_status: str | None = None
    companies_found: int
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    connectors_total: int
    connectors_completed: int
    message: str | None
    # Per-source counts and errors: managers and admins only.
    diagnostics: dict[str, Any] | None = None
    already_known: int | None = None  # matching companies LeadFinder already has (Find Leads returns new ones)


class LeadSearchResultOut(OutModel):
    rank: int | None
    relevance_score: float | None
    is_new: bool  # added to LeadFinder by this search (false = an already known company)
    source_count: int
    company: CompanyOut
