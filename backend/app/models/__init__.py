"""Import every model so Base.metadata is complete (used by Alembic)."""

from app.db.base import Base
from app.models.activity import LeadActivity
from app.models.audit import AuditLog
from app.models.campaign import Campaign, CampaignCompany
from app.models.company import Company
from app.models.contact import Contact
from app.models.lusha_usage import LushaUsage
from app.models.odoo_match import OdooMatch
from app.models.user import User, UserSession

__all__ = [
    "AuditLog",
    "Base",
    "Campaign",
    "CampaignCompany",
    "Company",
    "Contact",
    "LeadActivity",
    "LushaUsage",
    "OdooMatch",
    "User",
    "UserSession",
]
