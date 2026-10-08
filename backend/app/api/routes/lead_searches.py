from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DbSession, Pagination
from app.schemas.common import Page
from app.schemas.lead_search import LeadSearchCreate, LeadSearchOut, LeadSearchResultOut
from app.services import permissions, search_service
from app.services.pagination import page_response

router = APIRouter(prefix="/lead-searches", tags=["lead searches"])


def _out(db, user, search) -> LeadSearchOut:
    out = LeadSearchOut.model_validate(search)
    out.diagnostics = search.progress if permissions.is_privileged(user) else None
    out.enrichment_status = search_service.research_status(db, search.id)
    return out


@router.post("", response_model=LeadSearchOut, status_code=status.HTTP_201_CREATED)
def create_lead_search(payload: LeadSearchCreate, user: CurrentUser, db: DbSession):
    """Persists the search, answers it from LeadFinder's database first, and queues discovery for whatever
    is missing. Returns immediately (status `researching` while discovery runs)."""
    return _out(db, user, search_service.create_search(db, user, payload))


@router.get("/{search_id}", response_model=LeadSearchOut)
def get_lead_search(search_id: int, user: CurrentUser, db: DbSession):
    return _out(db, user, search_service.get_search(db, user, search_id))


@router.get("/{search_id}/results", response_model=Page[LeadSearchResultOut])
def lead_search_results(search_id: int, user: CurrentUser, db: DbSession, params: Pagination):
    items, total = search_service.list_results(db, user, search_id, params)
    return page_response(items, total, params)
