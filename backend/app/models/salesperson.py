from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class Salesperson(TimestampMixin, Base):
    """A TECOMSA salesperson as known to Odoo.

    Created automatically from the "Salesperson" column of Odoo imports and
    optionally linked to a LeadFinder user account by an administrator.
    """

    __tablename__ = "salespeople"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), unique=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Lower-cased, whitespace-collapsed name used to match Odoo exports.
    name_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(320))
    odoo_user_id: Mapped[int | None] = mapped_column(Integer, index=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())
    # The import that first created this record; used to undo an import's data.
    created_by_import_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_runs.id", ondelete="SET NULL"), index=True
    )

    user: Mapped["User | None"] = relationship(lazy="selectin")
