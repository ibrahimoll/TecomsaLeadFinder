"""Records imported from TECOMSA's Odoo (CSV/XLSX exports in Phase 0, API later).

Original Odoo identifiers are preserved. `source_key` makes re-imports idempotent:
it is the numeric Odoo id, the external id, or (when the export has neither) a
hash of the record's identifying fields.
"""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    false,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import CrmLeadType, sql_in

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.salesperson import Salesperson


class OdooContact(TimestampMixin, Base):
    """An Odoo res.partner record (a company or a person)."""

    __tablename__ = "odoo_contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    odoo_contact_id: Mapped[int | None] = mapped_column(Integer, index=True)
    odoo_external_id: Mapped[str | None] = mapped_column(String(255))
    contact_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_company: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    parent_company: Mapped[str | None] = mapped_column(String(255))
    website: Mapped[str | None] = mapped_column(String(500))
    domain: Mapped[str | None] = mapped_column(String(255), index=True)
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(50))
    mobile: Mapped[str | None] = mapped_column(String(50))
    phone_normalized: Mapped[str | None] = mapped_column(String(20), index=True)
    address: Mapped[str | None] = mapped_column(String(500))
    country: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str | None] = mapped_column(String(100))
    is_customer: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    salesperson_name: Mapped[str | None] = mapped_column(String(200))
    salesperson_id: Mapped[int | None] = mapped_column(
        ForeignKey("salespeople.id", ondelete="SET NULL"), index=True
    )
    # Normalised matching keys (see services/normalization.py).
    company_key: Mapped[str | None] = mapped_column(String(255), index=True)
    email_domain: Mapped[str | None] = mapped_column(String(255), index=True)
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )
    import_run_id: Mapped[int | None] = mapped_column(ForeignKey("import_runs.id", ondelete="SET NULL"))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    salesperson: Mapped["Salesperson | None"] = relationship(lazy="selectin")
    company: Mapped["Company | None"] = relationship(lazy="selectin")

    @property
    def organisation_name(self) -> str | None:
        """The company this partner represents or belongs to."""
        return self.contact_name if self.is_company else self.parent_company


class CrmLead(TimestampMixin, Base):
    """An Odoo crm.lead record (lead or opportunity)."""

    __tablename__ = "crm_leads"
    __table_args__ = (CheckConstraint(sql_in("lead_type", CrmLeadType), name="lead_type_valid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    odoo_lead_id: Mapped[int | None] = mapped_column(Integer, index=True)
    odoo_external_id: Mapped[str | None] = mapped_column(String(255))
    opportunity_name: Mapped[str] = mapped_column(String(500), nullable=False)
    company_name: Mapped[str | None] = mapped_column(String(255))
    contact_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(50))
    mobile: Mapped[str | None] = mapped_column(String(50))
    website: Mapped[str | None] = mapped_column(String(500))
    city: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str | None] = mapped_column(String(100))
    salesperson_name: Mapped[str | None] = mapped_column(String(200))
    salesperson_id: Mapped[int | None] = mapped_column(
        ForeignKey("salespeople.id", ondelete="SET NULL"), index=True
    )
    sales_team: Mapped[str | None] = mapped_column(String(200))
    stage: Mapped[str | None] = mapped_column(String(200))
    lead_type: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=CrmLeadType.OPPORTUNITY.value
    )
    expected_revenue: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    probability: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())
    is_won: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    lost_reason: Mapped[str | None] = mapped_column(Text)
    created_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_activity: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Normalised matching keys (see services/normalization.py).
    company_key: Mapped[str | None] = mapped_column(String(255), index=True)
    domain: Mapped[str | None] = mapped_column(String(255), index=True)
    email_domain: Mapped[str | None] = mapped_column(String(255), index=True)
    phone_normalized: Mapped[str | None] = mapped_column(String(20), index=True)
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )
    import_run_id: Mapped[int | None] = mapped_column(ForeignKey("import_runs.id", ondelete="SET NULL"))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    salesperson: Mapped["Salesperson | None"] = relationship(lazy="selectin")
    company: Mapped["Company | None"] = relationship(lazy="selectin")

    @property
    def is_lost(self) -> bool:
        return not self.is_won and (not self.active or bool(self.lost_reason))

    @property
    def is_open(self) -> bool:
        return self.active and not self.is_won and not self.lost_reason
