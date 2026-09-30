"""Seed FICTIONAL development data. Refuses to run in staging/production.

Usage:
    python -m scripts.seed_dev            # users only
    python -m scripts.seed_dev --companies  # users + three fictional demo companies

All seeded people and companies are fictional and clearly labelled as demo data.
"""

import argparse
import sys

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Company, User
from app.models.enums import CompanySource, UserRole
from app.schemas.company import CompanyCreate
from app.schemas.user import UserCreate
from app.services import company_service, user_service

DEV_PASSWORD = "LeadFinder-Dev-2026!"

DEMO_USERS = [
    ("Demo Admin (fictional)", "demo.admin@example.com", UserRole.ADMIN),
    ("Demo Sales Manager (fictional)", "demo.manager@example.com", UserRole.SALES_MANAGER),
    ("Demo Sales Agent One (fictional)", "demo.agent1@example.com", UserRole.SALES_AGENT),
    ("Demo Sales Agent Two (fictional)", "demo.agent2@example.com", UserRole.SALES_AGENT),
]

DEMO_COMPANIES = [
    ("Demo Manufacturing Company", "Manufacturing"),
    ("Demo Restaurant Group", "Restaurants"),
    ("Demo Trading Company", "Trading & Distribution"),
]
DEMO_DESCRIPTION = "FICTIONAL development seed record. Not a real company."


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed fictional development data")
    parser.add_argument("--companies", action="store_true", help="also create demo companies")
    args = parser.parse_args()

    settings = get_settings()
    if settings.environment not in ("development", "test"):
        print(f"Refusing to seed demo data in '{settings.environment}'.", file=sys.stderr)
        return 1

    with SessionLocal() as db:
        for name, email, role in DEMO_USERS:
            if db.scalar(select(User).where(User.email == email)):
                print(f"exists  {email}")
                continue
            user_service.create_user(
                db, None, UserCreate(name=name, email=email, password=DEV_PASSWORD, role=role)
            )
            print(f"created {email} ({role.value})")

        if args.companies:
            agent = db.scalar(select(User).where(User.email == "demo.agent1@example.com"))
            for name, industry in DEMO_COMPANIES:
                if db.scalar(select(Company).where(Company.name == name)):
                    print(f"exists  {name}")
                    continue
                company = company_service.create_company(
                    db,
                    agent,
                    CompanyCreate(
                        name=name, country="Lebanon", industry=industry, description=DEMO_DESCRIPTION
                    ),
                )
                company.source = CompanySource.DEMO  # never mistaken for real or Odoo data
                db.commit()
                print(f"created {name}")

    print(f"\nAll demo users share the development password: {DEV_PASSWORD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
