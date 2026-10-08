"""The ingestion contract every discovery source follows.

A connector turns a search into CompanyCandidate objects and NEVER touches the database. Every
candidate then passes through the same pipeline, once, for every source:

    connector -> CompanyCandidate -> normalizer -> consolidation (same company within the batch)
              -> deduplication (against the master database) -> persistence (company, source, evidence)

A candidate is transient: what a source said about one company, at one moment. Sources never get
their own permanent company fields; anything source-specific stays in `raw_metadata`.
"""

import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from app.models.enums import SOURCE_TYPES
from app.services.discovery.geography import Area, Country
from app.services.discovery.industries import CustomProfile, IndustryProfile

# Map editors' explicit closure markers in a name: "ABC Foods (closed)", "… - permanently closed",
# "(مغلق)". A bare word "closed" inside a name is not evidence.
_CLOSED_NAME = re.compile(r"\(\s*(permanently\s+)?closed\s*\)|permanently\s+closed|\bclosed\s+down\b|\(\s*مغلق\s*\)|مغلق نهائيا",
                          re.IGNORECASE)


def closed_reason(name: str) -> str | None:
    return "The source's name for it says it is closed." if _CLOSED_NAME.search(name) else None


@dataclass
class CompanyCandidate:
    # ---- provenance (required) ----
    connector: str  # connector key from connectors.json, e.g. "overture"
    source_name: str  # human-readable, e.g. "Overture Maps Places 2026-09-23.1"
    source_type: str  # one of enums.SOURCE_TYPES
    company_name: str  # as the source writes it (display value; normalized later, never overwritten)
    external_id: str | None = None  # the source's own id for the record
    source_url: str | None = None  # where a person can see the record
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # ---- what the source says about the company ----
    legal_name: str | None = None
    website: str | None = None
    domain: str | None = None  # only when the source states it separately from a website
    phone: str | None = None
    email: str | None = None
    country: str | None = None
    region: str | None = None
    city: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    industry: str | None = None  # the source's own label (raw); normalized later
    categories: list[str] = field(default_factory=list)  # the source's machine category keys (taxonomy path)
    sub_industry: str | None = None
    description: str | None = None
    employee_count: int | None = None
    registration_number: str | None = None  # official registry number, when the source is a registry
    brand: str | None = None  # brand / chain named by the source
    operator: str | None = None  # operating company named by the source (e.g. a franchisee)
    raw_metadata: dict[str, Any] = field(default_factory=dict)  # small subset of the raw record, for reprocessing

    # ---- how it matched the search (set by the connector) ----
    tier: str = "name"  # industry evidence tier, see industries.TIER_POINTS
    score: float = 0.0  # industry match strength (ranking)
    match_reason: str | None = None
    source_confidence: float | None = None  # the source's own 0-1 confidence, when it publishes one
    facility: str | None = None  # e.g. "Industrial site (OpenStreetMap: works)"
    datasets: list[str] = field(default_factory=list)  # independent datasets listing this place
    notes: list[str] = field(default_factory=list)  # source-specific concerns
    # Set when evidence rejects the record: CLOSED, WRONG_INDUSTRY, NOT_A_BUSINESS, INVALID.
    rejected: str | None = None
    reject_reason: str | None = None

    def __post_init__(self) -> None:
        self.company_name = " ".join((self.company_name or "").split())[:300]
        if self.source_type not in SOURCE_TYPES:
            raise ValueError(f"unknown source_type {self.source_type!r}")
        if not self.connector or not self.source_name:
            raise ValueError("a candidate must name its connector and source")
        if not self.company_name or not re.search(r"\w", self.company_name):
            self.rejected, self.reject_reason = "INVALID", "The record has no usable name."
        if self.latitude is not None and not -90 <= self.latitude <= 90 or \
                self.longitude is not None and not -180 <= self.longitude <= 180:
            self.latitude = self.longitude = None
        if self.employee_count is not None and self.employee_count <= 0:
            self.employee_count = None

    # V1 consolidation code reads `.name` / `.data`.
    @property
    def name(self) -> str:
        return self.company_name

    @property
    def data(self) -> dict[str, Any]:
        return self.raw_metadata


@dataclass
class SearchQuery:
    country: Country
    area: Area | None  # the requested city or region, when known
    industry: IndustryProfile | CustomProfile
    limit: int  # how many new companies are still needed (deficit + buffer)
    region_text: str | None = None
    city_text: str | None = None


@dataclass
class ConnectorResult:
    candidates: list[CompanyCandidate]  # best first
    version: str | None = None  # dataset release / snapshot used
    scanned: int = 0  # records the source looked at


class ConnectorError(Exception):
    """A source could not be queried. The message is safe to show to a salesperson."""


@dataclass(frozen=True)
class ConnectorConfig:
    """One entry of connectors.json (see config.py)."""

    key: str
    kind: str  # implementation: overture, osm, wikidata, dataset_file, public_web
    enabled: bool
    countries: tuple[str, ...]  # ISO codes; empty = every country the implementation supports
    priority: int  # lower runs first
    source_type: str
    quality: int  # 0-100 weight of this source (stored as sources.source_quality)
    requests_per_minute: int = 30
    label: str = ""
    options: dict[str, Any] = field(default_factory=dict)

    def supports(self, country_code: str) -> bool:
        return not self.countries or country_code in self.countries


class Connector(Protocol):
    config: ConnectorConfig

    def search_companies(self, query: SearchQuery) -> ConnectorResult: ...


def refresh_in_background(guard: threading.Lock, refresh: Callable[[], object], name: str) -> None:
    """Runs refresh() in a daemon thread unless one (holding `guard`) is already running. Connectors serve their
    cached copy meanwhile, so an expired cache never slows a search down; a failed refresh is only logged and the
    cached copy stays in use."""
    if not guard.acquire(blocking=False):
        return

    def target():
        try:
            refresh()
        except Exception:
            logging.getLogger(__name__).warning("Background refresh %s failed", name, exc_info=True)
        finally:
            guard.release()

    threading.Thread(target=target, name=name, daemon=True).start()
