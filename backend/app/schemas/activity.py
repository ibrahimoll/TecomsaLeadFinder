from datetime import datetime
from typing import Any

from pydantic import Field

from app.models.enums import ActivityType
from app.schemas.common import EntityRef, OutModel, UserBrief


class ContactRef(OutModel):
    id: int
    full_name: str


class ActivityOut(OutModel):
    id: int
    activity_type: ActivityType
    notes: str | None
    user: UserBrief | None
    company: EntityRef | None
    campaign: EntityRef | None
    contact: ContactRef | None
    created_at: datetime


class AuditLogOut(OutModel):
    id: int
    user: UserBrief | None
    action: str
    entity_type: str | None
    entity_id: str | None
    metadata: dict[str, Any] | None = Field(validation_alias="metadata_")
    created_at: datetime
