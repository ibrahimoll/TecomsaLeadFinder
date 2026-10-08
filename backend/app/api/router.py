from fastapi import APIRouter

from app.api.routes import audit, auth, companies, lead_searches, system, users

api_router = APIRouter()
for module in (system, auth, users, companies, lead_searches, audit):
    api_router.include_router(module.router)
