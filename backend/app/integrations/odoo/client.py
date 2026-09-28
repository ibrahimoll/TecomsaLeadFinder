"""Low-level Odoo transport (JSON-RPC / external API). NOT implemented in Phase 0.

Phase 1 will implement authenticated calls using ODOO_BASE_URL, ODOO_DATABASE and
ODOO_API_KEY (server-side only; never exposed to the frontend, never user passwords).
"""

from dataclasses import dataclass

from app.core.config import Settings
from app.integrations.base import IntegrationNotConfigured

PROVIDER = "Odoo"


@dataclass(frozen=True)
class OdooClientConfig:
    base_url: str | None
    database: str | None
    api_key: str | None

    @classmethod
    def from_settings(cls, settings: Settings) -> "OdooClientConfig":
        return cls(settings.odoo_base_url, settings.odoo_database, settings.odoo_api_key)

    @property
    def has_credentials(self) -> bool:
        return bool(self.base_url and self.database and self.api_key)


class OdooClient:
    def __init__(self, config: OdooClientConfig):
        self.config = config

    def execute(self, model: str, method: str, *args, **kwargs):
        # Intentionally no network call in Phase 0.
        raise IntegrationNotConfigured(PROVIDER, f"{model}.{method}")
