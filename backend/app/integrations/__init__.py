"""External provider integrations.

Every provider lives behind its own package (client / schemas / service) so it can be
replaced without touching the rest of the application. In Phase 0 all providers are
DISCONNECTED: their services raise IntegrationNotConfigured and make no network calls.
"""
