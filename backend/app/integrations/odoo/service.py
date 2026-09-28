"""Odoo CRM verification service - interface only (Phase 0: DISCONNECTED).

Phase 1 contract:
  check_company()     -> is this company already a contact / customer / opportunity in Odoo?
  find_contact()      -> look up an Odoo partner (person) by email/phone/name
  find_opportunity()  -> look up open crm.lead records for a partner

Callers must catch IntegrationNotConfigured and leave the company as NOT_CHECKED.
"""

from app.core.config import get_settings
from app.integrations.base import IntegrationNotConfigured
from app.integrations.odoo.client import PROVIDER, OdooClient, OdooClientConfig
from app.integrations.odoo.schemas import (
    OdooCompanyCheckResult,
    OdooCompanyQuery,
    OdooContactResult,
    OdooOpportunityResult,
)


class OdooService:
    connected = False  # flipped to True only when a real implementation exists

    def __init__(self, client: OdooClient):
        self.client = client

    def check_company(self, query: OdooCompanyQuery) -> OdooCompanyCheckResult:
        raise IntegrationNotConfigured(PROVIDER, "check_company")

    def find_contact(
        self, *, email: str | None = None, phone: str | None = None, name: str | None = None
    ) -> list[OdooContactResult]:
        raise IntegrationNotConfigured(PROVIDER, "find_contact")

    def find_opportunity(self, *, odoo_partner_id: int) -> list[OdooOpportunityResult]:
        raise IntegrationNotConfigured(PROVIDER, "find_opportunity")


def get_odoo_service() -> OdooService:
    return OdooService(OdooClient(OdooClientConfig.from_settings(get_settings())))
