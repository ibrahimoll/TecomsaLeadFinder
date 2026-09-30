from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import User
from app.models.enums import UserRole
from app.services import auth_service
from app.services.pagination import PageParams


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(request: Request, db: DbSession) -> User:
    token = request.cookies.get(get_settings().cookie_name)
    resolved = auth_service.resolve_session(db, token) if token else None
    if resolved is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    user, session = resolved
    request.state.session_id = session.id
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole):
    def dependency(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "You do not have permission to perform this action"
            )
        return user

    return dependency


AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]
ManagerOrAdmin = Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.SALES_MANAGER))]


def can_import(user: User) -> bool:
    """Admins always; Sales Managers only when MANAGERS_CAN_IMPORT is enabled."""
    return user.role == UserRole.ADMIN or (
        user.role == UserRole.SALES_MANAGER and get_settings().managers_can_import
    )


def require_importer(user: CurrentUser) -> User:
    if not can_import(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have permission to run Odoo imports")
    return user


ImportUser = Annotated[User, Depends(require_importer)]


def page_params(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> PageParams:
    return PageParams(page=page, page_size=page_size)


Pagination = Annotated[PageParams, Depends(page_params)]


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None
