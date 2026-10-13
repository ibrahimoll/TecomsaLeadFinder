import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.router import api_router
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.http_security import SecurityMiddleware
from app.core.owner_lock import OwnerLockMiddleware

logger = logging.getLogger("leadfinder")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if get_settings().is_production:
        _refuse_demo_accounts()
    from app.services import jobs

    if get_settings().discovery_worker_enabled:
        jobs.start_worker()  # discovery jobs run in a background thread, never in a request
    if get_settings().environment != "test":
        from app.services import company_lookup

        company_lookup.warm()  # the direct-search index of the cached extracts, built in the background
    yield
    jobs.stop_worker()


def _refuse_demo_accounts() -> None:
    """Fail closed: the fictional development accounts share a password published in the repository."""
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models import User

    with SessionLocal() as db:
        demo = db.scalars(select(User.email).where(User.is_active.is_(True), User.email.like("demo.%@example.com"))).all()
    if demo:
        raise RuntimeError(f"Refusing to start in production: {len(demo)} active development demo account(s) "
                           "(demo.*@example.com). Deactivate or delete them first.")


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=logging.INFO)

    app = FastAPI(
        lifespan=lifespan,
        title="TECOMSA LeadFinder API",
        version=__version__,
        # Interactive docs are only exposed outside production.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    app.add_middleware(OwnerLockMiddleware)  # while the owner has locked LeadFinder, nothing runs (inside CORS: readable)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
    )
    app.add_middleware(SecurityMiddleware)  # CSRF origin check, body size limit, security headers

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Log the full error server-side; never return stack traces to clients.
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    app.include_router(api_router)
    return app


app = create_app()
