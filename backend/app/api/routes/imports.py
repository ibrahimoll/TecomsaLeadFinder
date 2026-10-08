from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile, status

from app.api.deps import DbSession, ImportUser, Pagination
from app.core.config import get_settings
from app.core.exceptions import BusinessRuleError
from app.models.enums import ImportStatus, ImportType
from app.schemas.common import Page
from app.schemas.odoo import ImportDeleteResult, ImportPreview, ImportRunOut
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


@router.post("/{run_id}/confirm", response_model=ImportRunOut)
def confirm(run_id: int, user: ImportUser, db: DbSession):
    return import_service.confirm(db, user, run_id)


@router.post("/{run_id}/cancel", response_model=ImportRunOut)
def cancel(run_id: int, user: ImportUser, db: DbSession):
    return import_service.cancel(db, user, run_id)


@router.delete("/{run_id}", response_model=ImportDeleteResult)
def delete_import(run_id: int, user: ImportUser, db: DbSession, with_data: bool = False):
    """Delete an import from the history. `with_data=true` also removes the records only it created."""
    return import_service.delete_run(db, user, run_id, with_data=with_data)
