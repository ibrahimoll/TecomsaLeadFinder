"""PersonCandidate: one person-role claim read from one public source, before anything is stored.

Every source (the company's own pages today; conferences, associations, public documents later through a
PeopleSourceConnector) produces PersonCandidates; nothing writes people directly.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Protocol

from app.models import Company

# How much a source type is trusted for "this person holds this role at this company" (0-100).
SOURCE_QUALITY = {
    "team": 95,  # the company's own team / management / leadership page
    "news": 92,  # a company-owned announcement ("we are pleased to announce X as our new CFO")
    "about": 90,
    "contact": 85,
    "homepage": 85,
    "structured_data": 85,  # the company site's own Person / Organization metadata
    "company_document": 85,  # official PDF / annual report (connector, later)
    "careers": 75,
    "other": 75,
    "conference": 70,  # speaker / exhibitor biography naming the company (connector, later)
    "association": 70,
    "publication": 60,
    "directory": 45,
}


@dataclass
class PersonCandidate:
    source_id: int
    source_url: str | None
    source_type: str  # SOURCE_QUALITY key
    company_id: int
    full_name: str
    raw_title: str | None
    evidence_excerpt: str
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    first_name: str | None = None
    middle_name: str | None = None
    last_name: str | None = None
    normalized_title: str | None = None
    department: str | None = None
    seniority: str | None = None
    title_rank: int | None = None
    title_explicit: bool = False
    status: str = "current"  # current / former / unknown, as the evidence states it
    started_at: date | None = None
    ended_at: date | None = None
    location: str | None = None
    email: str | None = None  # only when published next to the person
    phone: str | None = None  # idem (E.164)
    profile_url: str | None = None
    biography: str | None = None
    source_confidence: int = 0
    company_match_confidence: int = 0  # how explicitly the source ties the person to this company
    person_confidence: int = 0
    raw_metadata: dict[str, Any] = field(default_factory=dict)


class PeopleSourceConnector(Protocol):
    """A permitted public source of people for a company (conference speakers, association members, public
    company documents...). Returns candidates; the engine normalizes, matches, resolves and stores them."""

    key: str

    def people(self, company: Company) -> list[PersonCandidate]: ...


# No external connector is configured yet: people come from the company's own website (Step 4 pages).
CONNECTORS: list[PeopleSourceConnector] = []
