import re
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.db.base import Base, TimestampMixin
from app.models.enums import IntegrationStatus, sql_in

# Keys that would hold credentials. `configuration` is plain JSONB, readable by anyone with database or
# backup access, so it only ever holds non-secret settings (base URL, database name, feature flags).
# Credentials stay in the deployment's secret store / environment until an encrypted store exists
# (APP_SECRET is reserved for that).
_SECRET_KEY = re.compile(r"pass(word|wd)?|secret|token|api[_-]?key|private[_-]?key|credential", re.IGNORECASE)


def secret_keys(value: Any, path: str = "") -> list[str]:
    """Paths of keys anywhere in `value` that look like they hold a credential."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            here = f"{path}.{key}" if path else str(key)
            if _SECRET_KEY.search(str(key)):
                found.append(here)
            found += secret_keys(item, here)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            found += secret_keys(item, f"{path}[{i}]")
    return found


class Integration(TimestampMixin, Base):
    __tablename__ = "integrations"
    __table_args__ = (CheckConstraint(sql_in("status", IntegrationStatus), name="status_valid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    integration_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)  # e.g. "odoo"
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False,
                                        server_default=IntegrationStatus.NOT_CONFIGURED.value)
    configuration: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    @validates("configuration")
    def _no_secrets(self, _key: str, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if leaked := secret_keys(value):
            raise ValueError(f"Integration configuration must not contain credentials: {', '.join(leaked)}")
        return value


class LushaRequest(TimestampMixin, Base):
    """Ledger of every paid Lusha call (services/lusha.py): a company's people search or one person's email / phone
    reveal - who, what, credits. One live (pending) or done reveal per Lusha contact and field: a double click or a
    second tab pays once (uq_lusha_requests_reveal); one run of the same search at a time (uq_lusha_requests_search).
    A search is reused by its search_key (company + normalized words + has-phone toggle + page)."""

    __tablename__ = "lusha_requests"
    __table_args__ = (
        CheckConstraint("action IN ('search', 'email', 'phone')", name="action_valid"),
        CheckConstraint("status IN ('pending', 'done', 'not_found', 'failed')", name="status_valid"),
        CheckConstraint("credits >= 0", name="credits_non_negative"),
        Index("uq_lusha_requests_reveal", "lusha_contact_id", "action", unique=True,
              postgresql_where=text("action <> 'search' AND status IN ('pending', 'done')")),
        Index("uq_lusha_requests_search", "search_key", unique=True,
              postgresql_where=text("action = 'search' AND status = 'pending'")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), index=True)
    person_id: Mapped[int | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"))  # who it saved
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    lusha_contact_id: Mapped[str | None] = mapped_column(String(200))  # reveals only
    search_key: Mapped[str | None] = mapped_column(String(300), index=True)  # searches only
    params: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # search: the query, filters sent, Lusha's total
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="pending")
    credits: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")  # Lusha's billing, else estimate
    # search: the people previews (no email / phone); reveal: the revealed values (stored so nobody pays twice)
    result: Mapped[Any | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(String(300))
