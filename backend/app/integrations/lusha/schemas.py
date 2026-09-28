"""Provider-neutral shapes for enrichment results (Phase 1+).

Lusha's own identifiers are carried as `provider_reference` and stored in
`contacts.source_reference` / `lusha_usage.provider_request_id`, never as our primary keys.
"""

from pydantic import BaseModel


class CompanySearchCriteria(BaseModel):
    country: str | None = None
    city: str | None = None
    industry: str | None = None
    company_size_min: int | None = None
    company_size_max: int | None = None
    limit: int = 25


class ContactSearchCriteria(BaseModel):
    company_domain: str | None = None
    company_name: str | None = None
    job_titles: list[str] = []
    limit: int = 10


class CompanyCandidate(BaseModel):
    provider_reference: str
    name: str
    domain: str | None = None
    country: str | None = None
    city: str | None = None
    industry: str | None = None
    employee_range: str | None = None


class ContactCandidate(BaseModel):
    provider_reference: str
    first_name: str
    last_name: str | None = None
    job_title: str | None = None
    seniority: str | None = None
    department: str | None = None


class RevealResult(BaseModel):
    provider_reference: str
    value: str | None
    credits_used: int
    provider_request_id: str | None = None
