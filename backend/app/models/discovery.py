"""Automatic company discovery (Phase 1).

A DiscoveryRun is one "Find companies" search. Every candidate it examined is kept as
a DiscoveryResult (also the ones that were already known or protected), so the user
can always see why a company was or was not added. CompanySourceRecord keeps the
provenance of each company: which external source (and source id) it came from.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import DiscoveryState, DiscoveryStatus, sql_in

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.user import User


class DiscoveryRun(TimestampMixin, Base):
    __tablename__ = "discovery_runs"
    __table_args__ = (CheckConstraint(sql_in("status", DiscoveryStatus), name="status_valid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    country: Mapped[str] = mapped_column(String(2), nullable=False)  # ISO 3166-1 alpha-2
    city: Mapped[str | None] = mapped_column(String(50))  # area key; NULL = whole country
    industry: Mapped[str | None] = mapped_column(String(50))  # industry key; NULL when custom
    custom_query: Mapped[str | None] = mapped_column(String(200))
    query_label: Mapped[str] = mapped_column(String(300), nullable=False)  # "Food Manufacturing · Lebanon"
    requested_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sources: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    source_version: Mapped[str | None] = mapped_column(String(200))  # e.g. Overture release
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=DiscoveryStatus.QUEUED.value, index=True
    )
    # Stage log shown as progress: [{"key", "label", "detail", "state"}]
    progress: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_match_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # matches in sources
    raw_results_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # candidates examined
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    existing_company_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    odoo_protected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    new_company_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    summary: Mapped[str | None] = mapped_column(Text)  # e.g. why fewer than requested were found

    creator: Mapped["User | None"] = relationship(lazy="selectin")


class DiscoveryResult(TimestampMixin, Base):
    __tablename__ = "discovery_results"
    __table_args__ = (CheckConstraint(sql_in("state", DiscoveryState), name="state_valid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("discovery_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)  # order examined within the run
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(200))
    address: Mapped[str | None] = mapped_column(String(500))
    city: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str | None] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(50))
    website: Mapped[str | None] = mapped_column(String(500))
    email: Mapped[str | None] = mapped_column(String(320))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(Text)  # why this state (matching evidence)
    match_reason: Mapped[str | None] = mapped_column(String(300))  # why it matched the industry
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )
    duplicate_of_id: Mapped[int | None] = mapped_column(
        ForeignKey("discovery_results.id", ondelete="SET NULL")
    )

    company: Mapped["Company | None"] = relationship(lazy="selectin")


class CompanySourceRecord(TimestampMixin, Base):
    """One external source record behind a company (provenance; re-discovery updates it)."""

    __tablename__ = "company_sources"
    __table_args__ = (UniqueConstraint("source", "external_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # What the source said (name, category, phone, website, email, address…) when last seen.
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    source_version: Mapped[str | None] = mapped_column(String(200))
    first_seen_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("discovery_runs.id", ondelete="SET NULL")
    )
    last_seen_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("discovery_runs.id", ondelete="SET NULL")
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
