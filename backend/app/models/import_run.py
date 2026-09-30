from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import ImportStatus, ImportType, sql_in

if TYPE_CHECKING:
    from app.models.user import User


class ImportRun(TimestampMixin, Base):
    """One uploaded file and what happened to it (preview → completed/failed/cancelled)."""

    __tablename__ = "import_runs"
    __table_args__ = (
        CheckConstraint(sql_in("import_type", ImportType), name="import_type_valid"),
        CheckConstraint(sql_in("status", ImportStatus), name="status_valid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    import_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=ImportStatus.PREVIEW.value, index=True
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(8), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # {target_field: source_column}
    column_mapping: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    detected_columns: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inserted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    companies_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    companies_linked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # First problems found, e.g. [{"row": 12, "level": "error", "message": "..."}]
    issues: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    failure_reason: Mapped[str | None] = mapped_column(String(1000))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    creator: Mapped["User | None"] = relationship(lazy="selectin")
