"""Read-side accounting over the `lusha_usage` ledger.

No Lusha API calls exist in Phase 0, so every total is 0. When the Lusha integration
is built, each credit-consuming call must append a LushaUsage row.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import LushaUsage


def total_credits(
    db: Session,
    *,
    company_id: int | None = None,
    campaign_id: int | None = None,
    user_id: int | None = None,
) -> int:
    stmt = select(func.coalesce(func.sum(LushaUsage.credits_used), 0))
    if company_id is not None:
        stmt = stmt.where(LushaUsage.company_id == company_id)
    if campaign_id is not None:
        stmt = stmt.where(LushaUsage.campaign_id == campaign_id)
    if user_id is not None:
        stmt = stmt.where(LushaUsage.user_id == user_id)
    return int(db.scalar(stmt) or 0)
