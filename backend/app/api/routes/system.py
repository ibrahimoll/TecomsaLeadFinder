from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select, text

from app import __version__
from app.api.deps import AdminUser, CurrentUser, DbSession
from app.core.config import get_settings
from app.models import Integration

router = APIRouter(tags=["system"])


class IntegrationStatusOut(BaseModel):
    name: str
    status: str
    detail: str


class SystemStatus(BaseModel):
    version: str
    environment: str
    integrations: list[IntegrationStatusOut]


@router.get("/health")
def health(db: DbSession) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}


@router.get("/settings/status", response_model=SystemStatus)
def system_status(_: AdminUser, db: DbSession):
    """Read-only application status. Integrations: what this deployment is actually configured with (never a
    credential), then any rows of the `integrations` table."""
    from app.services import lusha
    from app.services.agents import llm

    s = get_settings()
    state = lambda ok: "CONFIGURED" if ok else "NOT_CONFIGURED"  # noqa: E731
    live = [
        {"name": "Lusha", "status": state(lusha.configured()),
         "detail": "Paid people search and number reveals (LUSHA_API_KEY)"},
        {"name": "Local AI model", "status": state(s.agents_enabled and llm.available()),
         "detail": f"Company descriptions by the Profiler ({s.ollama_model}, runs on this machine)"},
        {"name": "Mailbox verification", "status": state(s.email_smtp_verification),
         "detail": "Checks predicted e-mails at the company's mail server (needs a clean static IP)"},
        {"name": "Map data (Overture / OpenStreetMap)", "status": "CONFIGURED",
         "detail": "Free public company and place data for Find Leads"},
    ]
    rows = db.scalars(select(Integration).order_by(Integration.display_name)).all()
    return {
        "version": __version__,
        "environment": s.environment,
        "integrations": live + [{"name": i.display_name, "status": i.status.upper(), "detail": i.integration_type}
                                for i in rows],
    }


@router.get("/agents/status")
def agents_status(_: CurrentUser, db: DbSession) -> dict:
    """What the Profiler and the Scout have done and are waiting for (counts only)."""
    from app.services.agents import llm, profiler, scout

    settings = get_settings()
    return {"enabled": settings.agents_enabled, "model": settings.ollama_model, "model_ready": llm.available(),
            "profiler": profiler.stats(db), "scout": scout.stats(db)}
