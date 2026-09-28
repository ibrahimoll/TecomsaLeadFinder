class IntegrationNotConfigured(Exception):
    """Raised when code tries to use a provider that is not connected.

    In Phase 0 this is raised unconditionally by every provider service: no
    Odoo, Lusha or AI calls are made, and no results are simulated.
    """

    def __init__(self, provider: str, operation: str):
        super().__init__(f"{provider} integration is not connected (attempted: {operation})")
        self.provider = provider
        self.operation = operation
