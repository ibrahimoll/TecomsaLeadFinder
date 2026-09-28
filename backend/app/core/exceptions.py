"""Domain exceptions raised by services and translated to HTTP responses in main.py."""


class AppError(Exception):
    status_code = 400

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class NotFoundError(AppError):
    status_code = 404


class PermissionDeniedError(AppError):
    status_code = 403


class ConflictError(AppError):
    status_code = 409


class BusinessRuleError(AppError):
    status_code = 422


class InvalidCredentialsError(Exception):
    """Login failed. Deliberately carries no detail about the reason."""
