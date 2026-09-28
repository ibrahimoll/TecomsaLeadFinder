from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import ContactSource

if TYPE_CHECKING:
    from app.models.company import Company


class Contact(TimestampMixin, Base):
    """A person at a company. Contacts belong to companies, never directly to campaigns."""

    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str | None] = mapped_column(String(100))
    job_title: Mapped[str | None] = mapped_column(String(200))
    department: Mapped[str | None] = mapped_column(String(100))
    seniority: Mapped[str | None] = mapped_column(String(50))
    business_email: Mapped[str | None] = mapped_column(String(320), index=True)
    business_phone: Mapped[str | None] = mapped_column(String(50))
    linkedin_url: Mapped[str | None] = mapped_column(String(500))
    # Provider-independent origin, e.g. MANUAL now; LUSHA / ODOO / IMPORT later.
    source: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=ContactSource.MANUAL.value
    )
    # The provider's own identifier for this contact (kept separate from our id).
    source_reference: Mapped[str | None] = mapped_column(String(255))
    data_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    company: Mapped["Company"] = relationship(back_populates="contacts")

    @property
    def full_name(self) -> str:
        return " ".join(part for part in (self.first_name, self.last_name) if part)
