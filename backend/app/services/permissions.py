"""Record-level authorization rules, enforced server-side.

V2 companies are one shared database: every signed-in user may read them, edit their basic fields and
move them through the sales statuses. Deleting a company is for managers and admins (route dependency).
Lead searches are personal history: agents see their own, managers and admins see everyone's.
"""

from app.models import User
from app.models.enums import UserRole

PRIVILEGED_ROLES = (UserRole.ADMIN, UserRole.SALES_MANAGER)


def is_privileged(user: User) -> bool:
    return user.role in PRIVILEGED_ROLES
