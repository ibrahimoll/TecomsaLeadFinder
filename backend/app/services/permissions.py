"""Record-level authorization rules. Enforced server-side for every request."""

from sqlalchemy import ColumnElement, true

from app.models import Campaign, Company, User
from app.models.enums import UserRole

PRIVILEGED_ROLES = (UserRole.ADMIN, UserRole.SALES_MANAGER)


def is_privileged(user: User) -> bool:
    return user.role in PRIVILEGED_ROLES


def campaign_visibility_filter(user: User) -> ColumnElement[bool]:
    """Agents see the campaigns they created; managers and admins see all campaigns."""
    if is_privileged(user):
        return true()
    return Campaign.created_by == user.id


def can_view_campaign(user: User, campaign: Campaign) -> bool:
    return is_privileged(user) or campaign.created_by == user.id


def can_manage_campaign(user: User, campaign: Campaign) -> bool:
    return is_privileged(user) or campaign.created_by == user.id


def can_edit_company(user: User, company: Company) -> bool:
    """All users can view the shared company database; agents edit only records they created."""
    return is_privileged(user) or company.created_by == user.id
