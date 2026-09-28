from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin
from app.models.enums import OdooMatchStatus, sql_in


class OdooMatch(CreatedAtMixin, Base):
    """Result of checking a company against TECOMSA's Odoo CRM.

    Phase 0 only ever writes NOT_CHECKED rows. Each future check appends a new row,
    so the history of checks is preserved; the latest row is the current status.
    """

    __tablename__ = "odoo_matches"
    __table_args__ = (
        CheckConstraint(sql_in("match_status", OdooMatchStatus), name="match_status_valid"),
        CheckConstraint(
            "match_confidence IS NULL OR (match_confidence >= 0 AND match_confidence <= 1)",
            name="match_confidence_range",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    odoo_partner_id: Mapped[int | None] = mapped_column(Integer, index=True)
    odoo_lead_id: Mapped[int | None] = mapped_column(Integer, index=True)
    match_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=OdooMatchStatus.NOT_CHECKED.value
    )
    match_confidence: Mapped[float | None] = mapped_column(Numeric(5, 4))
    match_reason: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
