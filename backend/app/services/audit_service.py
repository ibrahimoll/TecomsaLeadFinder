from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog
from app.services.pagination import PageParams, paginate


class AuditAction:
    LOGIN = "auth.login"
    LOGIN_FAILED = "auth.login_failed"
    LOGOUT = "auth.logout"
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    USER_DEACTIVATED = "user.deactivated"
    USER_ACTIVATED = "user.activated"
    COMPANY_CREATED = "company.created"
    COMPANY_UPDATED = "company.updated"
    COMPANY_STATUS_CHANGED = "company.status_changed"
    COMPANY_DELETED = "company.deleted"
    COMPANY_RESEARCH_REQUESTED = "company.research_requested"
    COMPANY_PERSON_CORRECTED = "company.person_corrected"
    LEAD_SEARCH_CREATED = "lead_search.created"


def record(
    db: Session,
    *,
    action: str,
    user_id: int | None,
    entity_type: str | None = None,
    entity_id: int | str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    """Add an audit entry to the current transaction (the caller commits)."""
    entry = AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        metadata_=metadata or None,
    )
    db.add(entry)
    return entry


def list_audit_logs(
    db: Session,
    params: PageParams,
    *,
    action: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    user_id: int | None = None,
) -> tuple[list[AuditLog], int]:
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    stmt = stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    return paginate(db, stmt, params)
