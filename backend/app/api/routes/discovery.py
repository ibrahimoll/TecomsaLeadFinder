from fastapi import APIRouter, status

from app.api.deps import AdminUser, CurrentUser, DbSession, Pagination
from app.schemas.common import Page
from app.schemas.discovery import (
    DiscoveryDeleteResult,
    DiscoveryResultsPage,
    DiscoveryRunCreate,
    DiscoveryRunOut,
)
from app.services.discovery import service as discovery_service
from app.services.pagination import page_response

router = APIRouter(prefix="/discovery", tags=["discovery"])


@router.get("/options")
def get_options(_: CurrentUser):
    """Countries, areas, industries and sources the search form can offer."""
    return discovery_service.options()


@router.post("/runs", response_model=DiscoveryRunOut, status_code=status.HTTP_202_ACCEPTED)
def start_run(payload: DiscoveryRunCreate, user: CurrentUser, db: DbSession):
    """Start a search. It runs in the background; poll GET /discovery/runs/{id} for progress."""
    return discovery_service.start_run(db, user, **payload.model_dump())


@router.get("/runs", response_model=Page[DiscoveryRunOut])
def list_runs(user: CurrentUser, db: DbSession, params: Pagination, mine: bool = False):
    items, total = discovery_service.list_runs(db, params, mine_only=user if mine else None)
    return page_response(items, total, params)


@router.get("/runs/{run_id}", response_model=DiscoveryRunOut)
def get_run(run_id: int, _: CurrentUser, db: DbSession):
    return discovery_service.get_run(db, run_id)


@router.get("/runs/{run_id}/results", response_model=DiscoveryResultsPage)
def list_results(run_id: int, _: CurrentUser, db: DbSession, params: Pagination, group: str | None = None,
                 source: str | None = None, q: str | None = None, sort: str = "rank"):
    items, total = discovery_service.list_results(db, run_id, params, group=group, source=source, q=q, sort=sort)
    return {**page_response(items, total, params), "counts": discovery_service.group_counts(db, run_id)}


@router.delete("/runs/{run_id}", response_model=DiscoveryDeleteResult)
def delete_run(run_id: int, user: AdminUser, db: DbSession, with_data: bool = False):
    """Admin only. `with_data=true` also removes companies only this run added and nothing else uses."""
    return discovery_service.delete_run(db, user, run_id, with_data=with_data)
