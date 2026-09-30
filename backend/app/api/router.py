from fastapi import APIRouter

from app.api.routes import (
    activities,
    audit,
    auth,
    campaigns,
    companies,
    contacts,
    imports,
    odoo,
    system,
    users,
)

api_router = APIRouter()
for module in (system, auth, users, companies, contacts, campaigns, activities, audit, imports, odoo):
    api_router.include_router(module.router)
