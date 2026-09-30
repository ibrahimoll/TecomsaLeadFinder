from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import InModel, OutModel, UserBrief


class SalespersonOut(OutModel):
    id: int
    name: str
    email: str | None
    odoo_user_id: int | None
    active: bool
    user: UserBrief | None
    created_at: datetime


class SalespersonRow(BaseModel):
    salesperson: SalespersonOut
    crm_records: int
    open_records: int
    odoo_contacts: int
    companies: int


class SalespersonUpdate(InModel):
    user_id: int | None = Field(default=None, gt=0)
    email: EmailStr | None = Field(default=None, max_length=320)
    odoo_user_id: int | None = Field(default=None, gt=0)
    active: bool | None = None
