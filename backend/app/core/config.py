"""Application settings, loaded from environment variables (and `.env` files)."""

import logging
from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_DEV_APP_SECRET = "dev-insecure-app-secret-do-not-use-in-production"
_DEV_JWT_SECRET = "dev-insecure-jwt-secret-do-not-use-in-production"
_MIN_SECRET_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Repo-root .env when run from backend/, or a local .env
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "test", "staging", "production"] = "development"

    database_url: str = "postgresql+psycopg://leadfinder:leadfinder@localhost:5432/leadfinder"

    # APP_SECRET is reserved for application-level signing/encryption
    # (e.g. encrypting integration credentials in later phases).
    app_secret: str = ""
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    session_expire_minutes: int = 480

    frontend_url: str = "http://localhost:3000"
    cors_extra_origins: str = ""

    cookie_name: str = "lf_session"
    cookie_secure: bool | None = None

    login_rate_limit_attempts: int = 10
    login_rate_limit_window_seconds: int = 300

    # Reserved for future phases - never required in Phase 0.
    odoo_base_url: str | None = None
    odoo_database: str | None = None
    odoo_api_key: str | None = None
    lusha_api_key: str | None = None
    ai_api_key: str | None = None

    @property
    def is_production(self) -> bool:
        return self.environment in ("staging", "production")

    @property
    def secure_cookies(self) -> bool:
        if self.cookie_secure is None:
            return self.is_production
        return self.cookie_secure

    @property
    def cors_origins(self) -> list[str]:
        origins = [self.frontend_url] + [o for o in self.cors_extra_origins.split(",")]
        return [o.strip().rstrip("/") for o in origins if o and o.strip()]

    @model_validator(mode="after")
    def _validate_secrets(self) -> "Settings":
        if self.is_production:
            for name in ("app_secret", "jwt_secret"):
                value = getattr(self, name)
                if len(value) < _MIN_SECRET_LENGTH or value in (_DEV_APP_SECRET, _DEV_JWT_SECRET):
                    raise ValueError(
                        f"{name.upper()} must be set to a random value of at least "
                        f"{_MIN_SECRET_LENGTH} characters in {self.environment}"
                    )
        else:
            if not self.app_secret:
                self.app_secret = _DEV_APP_SECRET
            if not self.jwt_secret:
                self.jwt_secret = _DEV_JWT_SECRET
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
