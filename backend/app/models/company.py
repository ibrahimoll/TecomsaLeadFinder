from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.contact import Contact
from app.models.enums import OdooMatchStatus
from app.models.odoo_match import OdooMatch

if TYPE_CHECKING:
    from app.models.user import User


class Company(TimestampMixin, Base):
    """One master record per real-world organisation.

    Name is deliberately NOT unique. `normalized_name` and `domain` are indexed
    to support identity resolution / duplicate detection in Phase 1.
    """

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    website: Mapped[str | None] = mapped_column(String(500))
    domain: Mapped[str | None] = mapped_column(String(255), index=True)
    country: Mapped[str | None] = mapped_column(String(100), index=True)
    city: Mapped[str | None] = mapped_column(String(100))
    industry: Mapped[str | None] = mapped_column(String(150), index=True)
    main_phone: Mapped[str | None] = mapped_column(String(50))
    # E.164 form (e.g. +9611234567) when it can be derived safely, else NULL.
    main_phone_normalized: Mapped[str | None] = mapped_column(String(20), index=True)
    main_email: Mapped[str | None] = mapped_column(String(320))
    company_size: Mapped[str | None] = mapped_column(String(20))
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    creator: Mapped["User | None"] = relationship(lazy="selectin")
    contacts: Mapped[list[Contact]] = relationship(
        back_populates="company", lazy="selectin", order_by=[Contact.created_at, Contact.id]
    )
    odoo_matches: Mapped[list[OdooMatch]] = relationship(
        lazy="selectin", order_by=[OdooMatch.created_at.desc(), OdooMatch.id.desc()]
    )

    @property
    def odoo_status(self) -> str:
        if not self.odoo_matches:
            return OdooMatchStatus.NOT_CHECKED
        return self.odoo_matches[0].match_status
