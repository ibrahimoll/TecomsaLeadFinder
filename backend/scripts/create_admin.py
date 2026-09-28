"""Create the initial LeadFinder administrator (safe for production).

Usage (inside the backend container or backend/ virtualenv):
    python -m scripts.create_admin --email admin@tecomsa.me --name "Jane Doe"

The password is prompted interactively, or read from LEADFINDER_ADMIN_PASSWORD
for non-interactive provisioning. It is never printed or logged.
"""

import argparse
import getpass
import os
import sys

from pydantic import ValidationError

from app.db.session import SessionLocal
from app.core.exceptions import ConflictError
from app.models.enums import UserRole
from app.schemas.user import UserCreate
from app.services import user_service


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a LeadFinder administrator")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--odoo-user-id", type=int, default=None)
    args = parser.parse_args()

    password = os.environ.get("LEADFINDER_ADMIN_PASSWORD")
    if not password:
        password = getpass.getpass("Password (min. 10 characters): ")
        if password != getpass.getpass("Repeat password: "):
            print("Passwords do not match.", file=sys.stderr)
            return 1

    try:
        data = UserCreate(
            name=args.name,
            email=args.email,
            password=password,
            role=UserRole.ADMIN,
            odoo_user_id=args.odoo_user_id,
        )
    except ValidationError as exc:
        print(f"Invalid input:\n{exc}", file=sys.stderr)
        return 1

    with SessionLocal() as db:
        try:
            user = user_service.create_user(db, None, data)
        except ConflictError as exc:
            print(exc.detail, file=sys.stderr)
            return 1
    print(f"Administrator created: {user.email} (id={user.id})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
