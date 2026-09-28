"""Lusha enrichment service - interface only (Phase 0: DISCONNECTED).

Future contract:
  search_companies()  -> company candidates for a campaign
  search_contacts()   -> decision-maker candidates at a company
  reveal_email()      -> credit-consuming email reveal
  reveal_phone()      -> credit-consuming phone reveal

When implemented, every credit-consuming call MUST append a `lusha_usage` row
(user, campaign, company, contact, action_type, credits_used, provider_request_id)
and respect `campaigns.max_lusha_credit_budget`.
"""

from app.core.config import get_settings
from app.integrations.base import IntegrationNotConfigured
from app.integrations.lusha.client import PROVIDER, LushaClient, LushaClientConfig
from app.integrations.lusha.schemas import (
    CompanyCandidate,
    CompanySearchCriteria,
    ContactCandidate,
    ContactSearchCriteria,
    RevealResult,
)


class LushaService:
    connected = False

    def __init__(self, client: LushaClient):
        self.client = client

    def search_companies(self, criteria: CompanySearchCriteria) -> list[CompanyCandidate]:
        raise IntegrationNotConfigured(PROVIDER, "search_companies")

    def search_contacts(self, criteria: ContactSearchCriteria) -> list[ContactCandidate]:
        raise IntegrationNotConfigured(PROVIDER, "search_contacts")

    def reveal_email(self, provider_reference: str) -> RevealResult:
        raise IntegrationNotConfigured(PROVIDER, "reveal_email")

    def reveal_phone(self, provider_reference: str) -> RevealResult:
        raise IntegrationNotConfigured(PROVIDER, "reveal_phone")


def get_lusha_service() -> LushaService:
    return LushaService(LushaClient(LushaClientConfig.from_settings(get_settings())))
