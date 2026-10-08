"""The shape every discovery source returns, and the small provider interface.

A provider turns a search (country, area, industry) into ranked Candidates. It never
touches the database: normalisation, duplicate checks, Odoo protection and saving are
done once, by the discovery service, for every source.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.services.discovery.geography import Area, Country
from app.services.discovery.industries import CustomProfile, IndustryProfile


@dataclass
class Candidate:
    source: str  # provider key, e.g. "OVERTURE"
    external_id: str  # the source's own id (Overture GERS id)
    name: str
    category: str | None = None  # human-readable source category
    website: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    city: str | None = None  # English name when known, else the source's locality
    country: str | None = None  # country name
    latitude: float | None = None
    longitude: float | None = None
    confidence: float | None = None  # the source's own confidence, when it has one
    score: float = 0.0  # how strongly it matched the requested industry
    match_reason: str | None = None
    data: dict[str, Any] = field(default_factory=dict)  # small provenance subset kept with the company


@dataclass
class SearchQuery:
    country: Country
    area: Area | None
    industry: IndustryProfile | CustomProfile


@dataclass
class SearchResult:
    candidates: list[Candidate]  # best first
    version: str | None = None  # dataset release / version used


class ProviderError(Exception):
    """A source could not be queried. The message is shown to the user."""


Progress = Callable[[str, str], None]  # (stage label, detail)


class DiscoveryProvider(Protocol):
    key: str
    label: str

    def search(self, query: SearchQuery, progress: Progress) -> SearchResult: ...
