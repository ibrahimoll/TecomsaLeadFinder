from fastapi import APIRouter
from sqlalchemy import text

from app import __version__
from app.api.deps import AdminUser, CurrentUser, DbSession
from app.core.config import get_settings
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
def system_status(_: AdminUser):
    """Read-only application status for administrators. Integrations are not managed here yet."""
    return {
        "version": __version__,
        "environment": get_settings().environment,
        "integrations": [
            {"name": "Odoo CRM", "status": "DISCONNECTED", "detail": "Planned for Phase 1. No calls are made."},
            {"name": "Lusha", "status": "DISCONNECTED", "detail": "Planned for a later phase. No credits are used."},
            {"name": "AI provider", "status": "DISCONNECTED", "detail": "Planned for a later phase."},
        ],
    }
