from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
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

    creator: Mapped["User | None"] = relationship(lazy="selectin")
    salesperson: Mapped["Salesperson | None"] = relationship(lazy="selectin")
    contacts: Mapped[list[Contact]] = relationship(
        back_populates="company", lazy="selectin", order_by=[Contact.created_at, Contact.id]
    )
    odoo_matches: Mapped[list[OdooMatch]] = relationship(
        lazy="select", order_by=[OdooMatch.created_at.desc(), OdooMatch.id.desc()]
    )

    @property
    def odoo_status(self) -> str:
        return self.crm_status or OdooMatchStatus.NOT_CHECKED

    @property
    def is_protected(self) -> bool:
        return self.crm_status in PROTECTED_STATUSES

    @property
    def source_label(self) -> str:
        return {"MANUAL": "Manual", "ODOO_IMPORT": "Odoo import", "DEMO": "Demo data"}.get(
            self.source, self.source
        )
