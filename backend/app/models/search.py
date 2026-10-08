from datetime import datetime
from typing import Any

from sqlalchemy import (Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, SmallInteger, String,
                        Text, UniqueConstraint, false, text)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin
from app.models.enums import LeadSearchStatus, ResearchRunStatus, SearchSolution, sql_in

MAX_REQUESTED_COUNT = 500


class LeadSearch(CreatedAtMixin, Base):
    """One Find Leads request, kept as search history."""

    __tablename__ = "lead_searches"
    __table_args__ = (
        CheckConstraint(sql_in("solution", SearchSolution), name="solution_valid"),
        CheckConstraint(sql_in("status", LeadSearchStatus), name="status_valid"),
        CheckConstraint(f"requested_count BETWEEN 1 AND {MAX_REQUESTED_COUNT}", name="requested_count_range"),
        CheckConstraint("companies_found >= 0", name="companies_found_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    country: Mapped[str] = mapped_column(String(100), nullable=False)
    region: Mapped[str | None] = mapped_column(String(120))
    city: Mapped[str | None] = mapped_column(String(120))
    industry: Mapped[str | None] = mapped_column(String(200))
    solution: Mapped[str] = mapped_column(String(16), nullable=False, server_default=SearchSolution.ANY.value)
    requested_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=LeadSearchStatus.PENDING.value)
    companies_found: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # NULL while pending: set when the discovery engine actually starts the search.
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    connectors_total: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    connectors_completed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # Per-connector counts and diagnostics (for admins); never raw exceptions or secrets.
    progress: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # One sentence a salesperson can read, e.g. why a search is partial.
    message: Mapped[str | None] = mapped_column(String(500))


class LeadSearchResult(CreatedAtMixin, Base):
    """A company returned by a search. Companies are shared: a result never copies the company."""

    __tablename__ = "lead_search_results"
    # One row per company per search (its index also serves lookups by search_id).
    __table_args__ = (UniqueConstraint("search_id", "company_id", name="uq_lead_search_results_company"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    search_id: Mapped[int] = mapped_column(ForeignKey("lead_searches.id", ondelete="CASCADE"), nullable=False)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False,
                                            index=True)
    rank: Mapped[int | None] = mapped_column(Integer)
    relevance_score: Mapped[float | None] = mapped_column(Float)  # 0-1, deterministic (discovery/ranking.py)
    # True when this search added the company to the database, false when it reused a known one.
    is_new: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())


class ResearchRun(CreatedAtMixin, Base):
    """Persistence for future research / crawler jobs. Kept after the company or search is deleted."""

    __tablename__ = "research_runs"
    __table_args__ = (
        CheckConstraint(sql_in("status", ResearchRunStatus), name="status_valid"),
        # The job queue (services/jobs.py) takes queued runs by priority, then age.
        Index("ix_research_runs_queued", "priority", "created_at", postgresql_where=text("status = 'queued'")),
        # At most one active (queued or running) run per company and kind: asking again only raises its priority,
        # never a second job (services/jobs.ACTIVE).
        Index("uq_research_runs_active_company", "company_id", "research_type", unique=True,
              postgresql_where=text("status IN ('queued', 'running') AND company_id IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), index=True)
    search_id: Mapped[int | None] = mapped_column(ForeignKey("lead_searches.id", ondelete="SET NULL"), index=True)
    research_type: Mapped[str] = mapped_column(String(40), nullable=False)  # enums.RESEARCH_TYPES
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="50")  # lower runs first
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=ResearchRunStatus.QUEUED.value)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)
