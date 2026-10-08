from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.contact import Contact
from app.models.enums import PROTECTED_STATUSES, CompanySource, OdooMatchStatus
from app.models.odoo_match import OdooMatch

if TYPE_CHECKING:
    from app.models.salesperson import Salesperson
    from app.models.user import User


class Company(TimestampMixin, Base):
    """One master record per real-world organisation.

    Name is deliberately NOT unique. `normalized_name`, `domain`, `email_domain` and
    `main_phone_normalized` are indexed for deterministic duplicate matching.

    `crm_status` is the current TECOMSA relationship derived from imported Odoo data
    (denormalised for filtering); `odoo_matches` keeps the history of every change.
    """

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    website: Mapped[str | None] = mapped_column(String(500))
    domain: Mapped[str | None] = mapped_column(String(255), index=True)
    country: Mapped[str | None] = mapped_column(String(100), index=True)
    city: Mapped[str | None] = mapped_column(String(100))
    address: Mapped[str | None] = mapped_column(String(500))
    industry: Mapped[str | None] = mapped_column(String(150), index=True)
    main_phone: Mapped[str | None] = mapped_column(String(50))
    # E.164 form (e.g. +9611234567) when it can be derived safely, else NULL.
    main_phone_normalized: Mapped[str | None] = mapped_column(String(20), index=True)
    main_email: Mapped[str | None] = mapped_column(String(320))
    # Domain of main_email when it is a company domain (not gmail.com etc.).
    email_domain: Mapped[str | None] = mapped_column(String(255), index=True)
    company_size: Mapped[str | None] = mapped_column(String(20))
    # Location of the (main) premises when a source supplies it (e.g. Overture Maps).
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    description: Mapped[str | None] = mapped_column(Text)
    # Where the record came from: MANUAL, ODOO_IMPORT, DEMO; later other discovery sources.
    source: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=CompanySource.MANUAL.value, index=True
    )
    source_reference: Mapped[str | None] = mapped_column(String(255))
    # The Odoo res.partner id of this company, when known.
    odoo_contact_id: Mapped[int | None] = mapped_column(Integer, index=True)
    crm_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=OdooMatchStatus.NOT_CHECKED.value, index=True
    )
    crm_status_reason: Mapped[str | None] = mapped_column(Text)
    crm_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Owner of the relationship in Odoo (salesperson on the deciding CRM record).
    salesperson_id: Mapped[int | None] = mapped_column(
        ForeignKey("salespeople.id", ondelete="SET NULL"), index=True
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    # The discovery run that created this company; used to undo a run's data.
    created_by_discovery_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("discovery_runs.id", ondelete="SET NULL"), index=True
    )
    # The import that first created this record; used to undo an import's data.
    created_by_import_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_runs.id", ondelete="SET NULL"), index=True
    )

    creator: Mapped["User | None"] = relationship(lazy="selectin")
    salesperson: Mapped["Salesperson | None"] = relationship(lazy="selectin")
    contacts: Mapped[list[Contact]] = relationship(
        back_populates="company", lazy="selectin", order_by=[Contact.created_at, Contact.id],
        cascade="all, delete-orphan", passive_deletes=True,
    )
    # History rows are removed by the database (ON DELETE CASCADE) with the company.
    odoo_matches: Mapped[list[OdooMatch]] = relationship(
        lazy="select", order_by=[OdooMatch.created_at.desc(), OdooMatch.id.desc()],
        cascade="all, delete-orphan", passive_deletes=True,
    )

    @property
    def odoo_status(self) -> str:
        return self.crm_status or OdooMatchStatus.NOT_CHECKED

    @property
    def is_protected(self) -> bool:
        return self.crm_status in PROTECTED_STATUSES

    @property
    def source_label(self) -> str:
        if self.source == CompanySource.DISCOVERY:
            return "Overture Maps" if (self.source_reference or "").startswith("overture:") else "Discovery"
        if self.source == CompanySource.ODOO_IMPORT:
            ref = self.source_reference or ""
            if ref.startswith("odoo-contacts-import:"):
                return "Odoo contact import"
            if ref.startswith("odoo-crm-import:"):
                return "Odoo CRM import"
        return {"MANUAL": "Manual", "ODOO_IMPORT": "Odoo import", "DEMO": "Demo data", "DISCOVERY": "Discovery"}.get(
            self.source, self.source
        )
