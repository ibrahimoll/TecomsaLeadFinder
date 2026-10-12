from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.enums import UserRole
from app.schemas.common import InModel, OutModel, require_value

PASSWORD_MIN = 10
PASSWORD_MAX = 256


class UserOut(OutModel):
    id: int
    name: str
    email: str
    role: UserRole
    odoo_user_id: int | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None


class Capabilities(BaseModel):
    """What the current user may do; the frontend uses it only to shape navigation."""

    manage_users: bool
    run_imports: bool = False


class MeOut(UserOut):
    capabilities: Capabilities


class UserCreate(InModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr = Field(max_length=320)
    password: str = Field(min_length=PASSWORD_MIN, max_length=PASSWORD_MAX)
    role: UserRole
    odoo_user_id: int | None = Field(default=None, gt=0)
    is_active: bool = True


class UserUpdate(InModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    email: EmailStr | None = Field(default=None, max_length=320)
    password: str | None = Field(default=None, min_length=PASSWORD_MIN, max_length=PASSWORD_MAX)
    role: UserRole | None = None
    odoo_user_id: int | None = Field(default=None, gt=0)
    is_active: bool | None = None

    @field_validator("name", "email", "role", "is_active")
    @classmethod
    def _not_null(cls, v, info):
        return require_value(v, info.field_name)
