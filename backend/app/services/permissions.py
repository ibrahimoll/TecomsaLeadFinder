"""Record-level authorization rules, enforced server-side.

Each company belongs to the lead generator who found it first (Company.owner_user_id): salespeople see, edit and
work only their own companies; managers and admins see everyone's and reassign them. Deleting a company is for
managers and admins (route dependency). Lead searches are personal history too: agents see their own, managers
and admins see everyone's.
"""

from app.models import Company, User
from app.models.enums import UserRole

PRIVILEGED_ROLES = (UserRole.ADMIN, UserRole.SALES_MANAGER)


def is_privileged(user: User) -> bool:
    return user.role in PRIVILEGED_ROLES


def can_see(user: User, company: Company | None) -> bool:
    return company is not None and (is_privileged(user) or company.owner_user_id == user.id)
