"""Low-level Lusha HTTP transport. NOT implemented in Phase 0.

LUSHA_API_KEY is read server-side only and must never reach the frontend.
"""

from dataclasses import dataclass

from app.core.config import Settings
from app.integrations.base import IntegrationNotConfigured

PROVIDER = "Lusha"


@dataclass(frozen=True)
class LushaClientConfig:
    api_key: str | None

    @classmethod
    def from_settings(cls, settings: Settings) -> "LushaClientConfig":
        return cls(settings.lusha_api_key)

    @property
    def has_credentials(self) -> bool:
        return bool(self.api_key)


class LushaClient:
    def __init__(self, config: LushaClientConfig):
        self.config = config

    def request(self, method: str, path: str, **kwargs):
        # Intentionally no network call in Phase 0 - zero credits are consumed.
        raise IntegrationNotConfigured(PROVIDER, f"{method} {path}")
