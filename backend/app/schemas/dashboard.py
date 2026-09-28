from pydantic import BaseModel

from app.schemas.activity import ActivityOut
from app.schemas.company import CompanyOut


class DashboardSummary(BaseModel):
    total_companies: int
    my_campaigns: int
    draft_campaigns: int
    lusha_credits_used: int
    recent_companies: list[CompanyOut]
    recent_activity: list[ActivityOut]


class IntegrationStatus(BaseModel):
    name: str
    status: str
    detail: str


class SystemStatus(BaseModel):
    version: str
    environment: str
    integrations: list[IntegrationStatus]
