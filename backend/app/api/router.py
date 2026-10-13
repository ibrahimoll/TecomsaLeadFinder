from fastapi import APIRouter

from app.api.deps import CompanyAccess
from app.api.routes import audit, auth, companies, imports, lead_searches, lusha, odoo, system, users

api_router = APIRouter()
for module in (system, auth, users, companies, lead_searches, imports, audit, odoo):
    api_router.include_router(module.router)
api_router.include_router(lusha.router, dependencies=[CompanyAccess])  # /companies/{company_id}/lusha...
