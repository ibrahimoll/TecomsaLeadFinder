from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import AdminUser, DbSession, Pagination
from app.schemas.audit import AuditLogOut
from app.schemas.common import Page
from app.services import audit_service
from app.services.pagination import page_response

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=Page[AuditLogOut])
def list_audit_logs(
    _: AdminUser,
    db: DbSession,
    params: Pagination,
    action: Annotated[str | None, Query(max_length=64)] = None,
    entity_type: Annotated[str | None, Query(max_length=64)] = None,
    entity_id: Annotated[str | None, Query(max_length=64)] = None,
    user_id: int | None = None,
):
    items, total = audit_service.list_audit_logs(
        db, params, action=action, entity_type=entity_type, entity_id=entity_id, user_id=user_id
    )
    return page_response(items, total, params)
