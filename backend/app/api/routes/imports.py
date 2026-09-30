from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile, status

from app.api.deps import DbSession, ImportUser, Pagination
from app.core.config import get_settings
from app.core.exceptions import BusinessRuleError
from app.models.enums import ImportStatus, ImportType
from app.schemas.common import Page
from app.schemas.odoo import ImportMappingUpdate, ImportPreview, ImportRunOut
from app.services import import_service
from app.services.pagination import page_response

router = APIRouter(prefix="/imports", tags=["imports"])


@router.get("", response_model=Page[ImportRunOut])
def list_imports(
    _: ImportUser,
    db: DbSession,
    params: Pagination,
    import_type: ImportType | None = None,
    status: ImportStatus | None = None,
):
    items, total = import_service.list_runs(db, params, import_type=import_type, status=status)
    return page_response(items, total, params)


@router.post("", response_model=ImportPreview, status_code=status.HTTP_201_CREATED)
def upload(
    user: ImportUser,
    db: DbSession,
    import_type: Annotated[ImportType, Form()],
    file: Annotated[UploadFile, File()],
):
    """Upload a CSV/XLSX export. Returns a preview; nothing is imported until confirmed."""
    limit = get_settings().import_max_bytes
    content = file.file.read(limit + 1)
    if len(content) > limit:
        raise BusinessRuleError(f"The file is larger than {limit // (1024 * 1024)} MB.")
    run = import_service.create_upload(db, user, import_type, file.filename or "upload", content)
    return import_service.build_preview(db, run)


@router.get("/{run_id}", response_model=ImportRunOut)
def get_import(run_id: int, _: ImportUser, db: DbSession):
    return import_service.get_run(db, run_id)


@router.get("/{run_id}/preview", response_model=ImportPreview)
def get_preview(run_id: int, _: ImportUser, db: DbSession):
    return import_service.build_preview(db, import_service.get_run(db, run_id))


@router.put("/{run_id}/mapping", response_model=ImportPreview)
def update_mapping(run_id: int, payload: ImportMappingUpdate, user: ImportUser, db: DbSession):
    run = import_service.update_mapping(db, user, run_id, payload.mapping)
    return import_service.build_preview(db, run)


@router.post("/{run_id}/confirm", response_model=ImportRunOut)
def confirm(run_id: int, user: ImportUser, db: DbSession):
    return import_service.confirm(db, user, run_id)


@router.post("/{run_id}/cancel", response_model=ImportRunOut)
def cancel(run_id: int, user: ImportUser, db: DbSession):
    return import_service.cancel(db, user, run_id)
