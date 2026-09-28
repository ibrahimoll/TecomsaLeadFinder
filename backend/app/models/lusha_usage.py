from sqlalchemy import CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin
from app.models.enums import LushaActionType, sql_in


class LushaUsage(CreatedAtMixin, Base):
    """Ledger of Lusha credit consumption. Empty in Phase 0 (no Lusha calls are made)."""

    __tablename__ = "lusha_usage"
    __table_args__ = (
        CheckConstraint(sql_in("action_type", LushaActionType), name="action_type_valid"),
        CheckConstraint("credits_used >= 0", name="credits_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    campaign_id: Mapped[int | None] = mapped_column(
        ForeignKey("campaigns.id", ondelete="SET NULL"), index=True
    )
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"))
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    credits_used: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    provider_request_id: Mapped[str | None] = mapped_column(String(255))
