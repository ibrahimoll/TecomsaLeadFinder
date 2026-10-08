"""Seed FICTIONAL development data. Refuses to run in staging/production.

Usage:
    python -m scripts.seed_dev              # demo users only
    python -m scripts.seed_dev --companies  # demo users + fictional V2 business data

Every seeded company, person and contact point is fictional and marked as such: company names end in
"(demo)", descriptions say so, domains use the reserved `.example` TLD (they cannot exist), phone numbers
are in an unused 000 block, and every source carries metadata {"dev_seed": true}. Running it twice adds
nothing new.
"""

import argparse
import sys
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import (CompanyLocation, CompanyPerson, Email, Evidence, OpportunityAnalysis, Person, Phone, Source,
                        User)
from app.models.enums import UserRole
from app.schemas.company import CompanyCreate
from app.schemas.user import UserCreate
from app.services import company_service, user_service
from app.services.normalization import name_key, normalize_phone

DEV_PASSWORD = "LeadFinder-Dev-2026!"

DEMO_USERS = [
    ("Demo Admin (fictional)", "demo.admin@example.com", UserRole.ADMIN),
    ("Demo Sales Manager (fictional)", "demo.manager@example.com", UserRole.SALES_MANAGER),
    ("Demo Sales Agent One (fictional)", "demo.agent1@example.com", UserRole.SALES_AGENT),
    ("Demo Sales Agent Two (fictional)", "demo.agent2@example.com", UserRole.SALES_AGENT),
]

SEED_MARK = {"dev_seed": True}
DESCRIPTION = "FICTIONAL development seed record. Not a real company."
NOW = datetime.now(timezone.utc)

# name, domain, industry, hq (country, region, city), status, locations, people, opportunities
COMPANIES = [
    {
        "name": "Cedar Valley Foods (demo)", "domain": "cedarvalleyfoods.example", "industry": "Food Manufacturing",
        "sub_industry": "Dairy and snacks", "employees": 180, "founded": 1998, "status": "qualified",
        "hq": ("Lebanon", "Bekaa", "Zahle"), "phone": "+961 8 000 101", "email": "info@cedarvalleyfoods.example",
        "locations": [("factory", "Lebanon", "Bekaa", "Zahle", True), ("office", "Lebanon", "Beirut", "Beirut", False),
                      ("warehouse", "Lebanon", "Mount Lebanon", "Choueifat", False)],
        "people": [("Elias Haddad", "Chief Executive Officer", "executive", "c_level"),
                   ("Rami Khoury", "IT Manager", "it", "manager"),
                   ("Maya Saab", "Chief Financial Officer", "finance", "c_level"),
                   ("Tarek Nassar", "Procurement Manager", "procurement", "manager"),
                   ("Joseph Aoun", "Production Manager", "manufacturing", "manager")],
        "opportunities": [("odoo", "high", "Runs production, inventory and accounting on separate spreadsheets.",
                           ["Manufacturing", "Inventory", "Quality", "Accounting"]),
                          ("it", "medium", "Three sites without a shared network or backup policy.",
                           ["Site networking", "Backup"])],
    },
    {
        "name": "Phoenicia Retail Group (demo)", "domain": "phoeniciaretail.example", "industry": "Retail",
        "sub_industry": "Home goods", "employees": 75, "founded": 2009, "status": "contacted",
        "hq": ("Lebanon", "Beirut", "Beirut"), "phone": "+961 1 000 202", "email": "contact@phoeniciaretail.example",
        "locations": [("office", "Lebanon", "Beirut", "Beirut", True), ("store", "Lebanon", "Keserwan", "Jounieh", False),
                      ("store", "Lebanon", "South", "Saida", False)],
        "people": [("Nadine Frem", "Managing Director", "executive", "c_level"),
                   ("Karim Sleiman", "Marketing Manager", "marketing", "manager"),
                   ("Lara Mansour", "E-commerce Lead", "e_commerce", "head"),
                   ("Hiba Daher", "HR Manager", "hr", "manager")],
        "opportunities": [("frinzo", "medium", "Opening an online store alongside three physical branches.",
                           ["Online ordering"]),
                          ("odoo", "unknown", "Not enough public information yet.", None)],
    },
    {
        "name": "Gulfline Logistics (demo)", "domain": "gulflinelogistics.example", "industry": "Logistics",
        "sub_industry": "Freight forwarding", "employees": 40, "founded": 2015, "status": "new",
        "hq": ("Lebanon", "Beirut", "Beirut"), "phone": "+961 1 000 303", "email": None,
        "locations": [("headquarters", "Lebanon", "Beirut", "Beirut", True),
                      ("branch", "United Arab Emirates", "Dubai", "Dubai", False)],
        "people": [("Omar Itani", "Operations Director", "operations", "director"),
                   ("Sara Halabi", "Head of Sales", "sales", "head")],
        "opportunities": [],
    },
]


def seed_users(db) -> None:
    for name, email, role in DEMO_USERS:
        if db.scalar(select(User).where(User.email == email)):
            print(f"exists  {email}")
            continue
        user_service.create_user(db, None, UserCreate(name=name, email=email, password=DEV_PASSWORD, role=role))
        print(f"created {email} ({role.value})")


def seed_business(db) -> None:
    if db.scalar(select(Source.id).where(Source.metadata_["dev_seed"].as_boolean())):
        print("exists  demo business data (dev_seed sources found)")
        return
    agent = db.scalar(select(User).where(User.email == "demo.agent1@example.com"))
    for spec in COMPANIES:
        country, region, city = spec["hq"]
        company = company_service.create_company(db, agent, CompanyCreate(
            name=spec["name"], website=f"https://{spec['domain']}", description=DESCRIPTION,
            industry=spec["industry"], sub_industry=spec["sub_industry"], employee_count_estimate=spec["employees"],
            founded_year=spec["founded"], headquarters_country=country, headquarters_region=region,
            headquarters_city=city, primary_phone=spec["phone"], primary_email=spec["email"]))
        company.status = spec["status"]  # seed state, not a sales action: no status history

        site = Source(source_type="company_website", name=f"{spec['name']} website",
                      url=f"https://{spec['domain']}/about", publisher=spec["name"], retrieved_at=NOW,
                      source_quality=70, metadata_=SEED_MARK)
        team = Source(source_type="company_website", name=f"{spec['name']} team page",
                      url=f"https://{spec['domain']}/team", publisher=spec["name"], retrieved_at=NOW,
                      source_quality=70, metadata_=SEED_MARK)
        db.add_all([site, team])
        db.flush()

        for kind, loc_country, loc_region, loc_city, is_hq in spec["locations"]:
            db.add(CompanyLocation(company_id=company.id, location_type=kind, country=loc_country, region=loc_region,
                                   city=loc_city, is_headquarters=is_hq, source_id=site.id, confidence=80))
        db.add(Evidence(source_id=site.id, company_id=company.id, evidence_type="company_fact", field_name="industry",
                        extracted_value=spec["industry"], excerpt=f"{spec['name']} - {spec['sub_industry']}",
                        confidence=80, observed_at=NOW))
        db.add(Phone(company_id=company.id, phone=spec["phone"], normalized_phone=normalize_phone(spec["phone"]),
                     phone_type="landline", is_primary=True, is_public=True, status="discovered", confidence=80,
                     source_id=site.id, first_seen_at=NOW, last_seen_at=NOW))
        if spec["email"]:
            db.add(Email(company_id=company.id, email=spec["email"], email_type="generic", status="discovered",
                         is_primary=True, is_public=True, confidence=80, source_id=site.id, first_seen_at=NOW,
                         last_seen_at=NOW))

        for i, (full_name, title, department, seniority) in enumerate(spec["people"]):
            first, last = full_name.split(" ", 1)
            person = Person(full_name=full_name, first_name=first, last_name=last, normalized_name=name_key(full_name),
                            location_country=country)
            db.add(person)
            db.flush()
            role = CompanyPerson(company_id=company.id, person_id=person.id, job_title=title,
                                 normalized_title=title.lower(), department=department, seniority=seniority,
                                 confidence=75, first_seen_at=NOW, last_seen_at=NOW, primary_source_id=team.id)
            db.add(role)
            db.flush()
            db.add(Evidence(source_id=team.id, company_id=company.id, person_id=person.id, company_person_id=role.id,
                            evidence_type="employment", field_name="job_title", extracted_value=title,
                            excerpt=f"{full_name}, {title}", confidence=75, observed_at=NOW))
            address = f"{first}.{last}".lower().replace(" ", "") + f"@{spec['domain']}"
            if i == 0:  # the leader's address is published on the team page
                db.add(Email(company_id=company.id, person_id=person.id, email=address, email_type="work",
                             status="discovered", is_primary=True, is_public=True, confidence=75, source_id=team.id,
                             first_seen_at=NOW, last_seen_at=NOW))
            elif i == 1:  # a guessed first.last pattern: predicted, never verified
                db.add(Email(company_id=company.id, person_id=person.id, email=address, email_type="work",
                             status="predicted", confidence=40))
                db.add(Phone(company_id=company.id, person_id=person.id, phone=f"+961 3 000 {100 + i:03d}",
                             normalized_phone=normalize_phone(f"+961 3 000 {100 + i:03d}"), phone_type="mobile",
                             status="unknown", confidence=30, source_id=team.id))

        for solution, fit, summary, modules in spec["opportunities"]:
            db.add(OpportunityAnalysis(company_id=company.id, solution=solution, fit_level=fit,
                                       summary=f"Development example, not generated by AI. {summary}",
                                       recommended_modules_or_services=modules, signals=[summary], generated_at=NOW))
        db.commit()
        print(f"created {spec['name']}: {len(spec['locations'])} locations, {len(spec['people'])} people")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed fictional development data")
    parser.add_argument("--companies", action="store_true", help="also create fictional V2 business data")
    args = parser.parse_args()

    settings = get_settings()
    if settings.environment not in ("development", "test"):
        print(f"Refusing to seed demo data in '{settings.environment}'.", file=sys.stderr)
        return 1

    with SessionLocal() as db:
        seed_users(db)
        if args.companies:
            seed_business(db)

    print(f"\nAll demo users share the development password: {DEV_PASSWORD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
