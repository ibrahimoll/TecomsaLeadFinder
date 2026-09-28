from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import (
    CampaignCompanyStatus,
    CampaignStatus,
    Division,
    QualificationStatus,
    sql_in,
)

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.user import User


class Campaign(TimestampMixin, Base):
    __tablename__ = "campaigns"
    __table_args__ = (
        CheckConstraint(sql_in("tecomsa_division", Division), name="division_valid"),
        CheckConstraint(sql_in("status", CampaignStatus), name="status_valid"),
        CheckConstraint("target_company_count > 0", name="target_count_positive"),
        CheckConstraint(
            "max_lusha_credit_budget IS NULL OR max_lusha_credit_budget >= 0",
            name="lusha_budget_non_negative",
        ),
        CheckConstraint(
            "company_size_min IS NULL OR company_size_max IS NULL "
            "OR company_size_min <= company_size_max",
            name="company_size_range",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    tecomsa_division: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    country: Mapped[str] = mapped_column(String(100), nullable=False)
    region: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str | None] = mapped_column(String(100))
    industry: Mapped[str | None] = mapped_column(String(150))
    company_size_min: Mapped[int | None] = mapped_column(Integer)
    company_size_max: Mapped[int | None] = mapped_column(Integer)
    target_roles: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    target_company_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # Stored only. No Lusha call happens in Phase 0.
    max_lusha_credit_budget: Mapped[int | None] = mapped_column(Integer)
    additional_instructions: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=CampaignStatus.DRAFT.value, index=True
    )

    creator: Mapped["User"] = relationship(lazy="selectin")


class CampaignCompany(TimestampMixin, Base):
    """Links a master company record to a campaign (companies are never duplicated per campaign)."""

    __tablename__ = "campaign_companies"
    __table_args__ = (
        UniqueConstraint("campaign_id", "company_id", name="uq_campaign_companies_campaign_company"),
        CheckConstraint(sql_in("status", CampaignCompanyStatus), name="status_valid"),
        CheckConstraint(
            sql_in("qualification_status", QualificationStatus), name="qualification_status_valid"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=CampaignCompanyStatus.ADDED.value
    )
    qualification_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=QualificationStatus.PENDING.value
    )
    added_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    campaign: Mapped["Campaign"] = relationship(lazy="selectin")
    company: Mapped["Company"] = relationship(lazy="selectin")
