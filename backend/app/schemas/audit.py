from datetime import datetime
from typing import Any

from pydantic import Field

from app.schemas.common import OutModel, UserBrief


class AuditLogOut(OutModel):
    id: int
    user: UserBrief | None
    action: str
    entity_type: str | None
    entity_id: str | None
    metadata: dict[str, Any] | None = Field(validation_alias="metadata_")
    created_at: datetime
