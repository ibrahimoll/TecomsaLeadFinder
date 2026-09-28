from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import AdminUser, DbSession, ManagerOrAdmin, Pagination
from app.models.enums import UserRole
from app.schemas.common import Page
from app.schemas.user import UserCreate, UserOut, UserUpdate
from app.services import user_service
from app.services.pagination import page_response

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=Page[UserOut])
def list_users(
    _: ManagerOrAdmin,
    db: DbSession,
    params: Pagination,
    q: Annotated[str | None, Query(max_length=200)] = None,
    role: UserRole | None = None,
    is_active: bool | None = None,
):
    items, total = user_service.list_users(db, params, q=q, role=role, is_active=is_active)
    return page_response(items, total, params)


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, admin: AdminUser, db: DbSession):
    return user_service.create_user(db, admin, payload)


@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: int, _: AdminUser, db: DbSession):
    return user_service.get_user(db, user_id)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, payload: UserUpdate, admin: AdminUser, db: DbSession):
    return user_service.update_user(db, admin, user_id, payload)
