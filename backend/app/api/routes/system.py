from fastapi import APIRouter
from sqlalchemy import func, select, text

from app import __version__
from app.api.deps import AdminUser, CurrentUser, DbSession
from app.core.config import get_settings
from app.models import ImportRun
from app.models.enums import ImportStatus
from app.schemas.dashboard import DashboardSummary, SystemStatus
from app.services import dashboard_service

router = APIRouter(tags=["system"])


@router.get("/health")
def health(db: DbSession) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}


@router.get("/dashboard", response_model=DashboardSummary)
def dashboard(user: CurrentUser, db: DbSession):
    return dashboard_service.get_summary(db, user)


@router.get("/settings/status", response_model=SystemStatus)
def system_status(_: AdminUser, db: DbSession):
    """Read-only application status. Integration states reflect reality: nothing
    external is connected in Phase 0, regardless of which env variables exist."""
    settings = get_settings()
    last_import = db.scalar(select(func.max(ImportRun.completed_at)).where(ImportRun.status == ImportStatus.COMPLETED))
    return {
        "version": __version__,
        "environment": settings.environment,
        "managers_can_import": settings.managers_can_import,
        "last_odoo_import_at": last_import,
        "integrations": [
            {"name": "Odoo file import (CSV / XLSX)", "status": "CONFIGURED",
             "detail": "Built in. Admins upload Odoo exports under Data sources → Odoo."},
            {"name": "Odoo API sync", "status": "NOT_CONFIGURED",
             "detail": "Not implemented in Phase 0. No calls are made to Odoo."},
            {"name": "Lusha", "status": "NOT_CONFIGURED", "detail": "Planned for a later phase. No credits are used."},
            {"name": "AI provider", "status": "NOT_CONFIGURED", "detail": "Planned for Phase 1 (company qualification)."},
        ],
    }
