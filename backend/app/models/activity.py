from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin
from app.models.enums import ActivityType, sql_in

if TYPE_CHECKING:
    from app.models.campaign import Campaign
    from app.models.company import Company
    from app.models.contact import Contact
    from app.models.user import User


class LeadActivity(CreatedAtMixin, Base):
    """Business event timeline (sales-facing). Structured for later ML use."""

    __tablename__ = "lead_activities"
    __table_args__ = (
        CheckConstraint(sql_in("activity_type", ActivityType), name="activity_type_valid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"))
    campaign_id: Mapped[int | None] = mapped_column(
        ForeignKey("campaigns.id", ondelete="SET NULL"), index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    activity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    user: Mapped["User | None"] = relationship(lazy="selectin")
    company: Mapped["Company | None"] = relationship(lazy="selectin")
    campaign: Mapped["Campaign | None"] = relationship(lazy="selectin")
    contact: Mapped["Contact | None"] = relationship(lazy="selectin")
