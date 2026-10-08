import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.router import api_router
from app.core.config import get_settings
from app.core.exceptions import AppError

logger = logging.getLogger("leadfinder")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Discovery runs execute in background threads; any left "running" by a previous
    # process can never finish, so mark them as interrupted.
    from app.db.session import SessionLocal
    from app.services.discovery.service import fail_interrupted_runs

    try:
        with SessionLocal() as db:
            count = fail_interrupted_runs(db)
            if count:
                logger.warning("Marked %s interrupted discovery run(s)", count)
    except Exception:  # never block startup on this
        logger.exception("Could not check for interrupted discovery runs")
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=logging.INFO)

    app = FastAPI(
        lifespan=lifespan,
        title="TECOMSA LeadFinder AI API",
        version=__version__,
        # Interactive docs are only exposed outside production.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

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
