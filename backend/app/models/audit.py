from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin

if TYPE_CHECKING:
    from app.models.user import User


class AuditLog(CreatedAtMixin, Base):
    """Security/compliance trail. Never store passwords, tokens or secrets in `metadata`."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    # `metadata` is reserved on declarative classes, hence the attribute name.
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)

    user: Mapped["User | None"] = relationship(lazy="selectin")
