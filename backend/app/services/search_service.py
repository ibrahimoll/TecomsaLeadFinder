"""Find Leads: a search is persisted, answered from LeadFinder's own database first, and only the missing
companies are discovered (asynchronously, by the job worker).

    POST /lead-searches
      1. persist the search (country / region / city normalized: 'Liban' -> Lebanon, 'Mount Lebanon' is a
         region, 'Jounieh' a city in Mount Lebanon)
      2. rank the matching companies already in the database -> lead_search_results (is_new = false)
      3. deficit = requested - found
         0          -> completed now, no external lookup at all
         > 0        -> researching: a discovery job is queued; the response returns immediately
         no source  -> partial: discovery is not available for that country yet
"""

import logging
import time

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models import Company, CompanyLocation, Evidence, LeadSearch, LeadSearchResult, User
from app.models.enums import CompanyStatus, EnrichmentStatus, LeadSearchStatus
from app.schemas.lead_search import LeadSearchCreate
from app.services import audit_service, jobs, permissions
from app.services.audit_service import AuditAction
from app.services.discovery.orchestrator import connector_configs, plan_for
from app.services.discovery.ranking import in_country, in_requested_area, industry_fit, load_facts, ordered
from app.services.pagination import PageParams

logger = logging.getLogger("leadfinder.discovery")
# Never offered as new leads.
EXCLUDED = (CompanyStatus.DO_NOT_CONTACT.value, CompanyStatus.ARCHIVED.value)
# ponytail: local matching scores up to this many companies of the country in Python; move the geography and
# industry filters into SQL (PostGIS / pg_trgm) when one country holds far more companies than this.
LOCAL_SCAN_LIMIT = 20_000


def _local_results(db: Session, search: LeadSearch) -> int:
    plan = plan_for(search)
    if plan.country is None:
        return 0
    names = (plan.country.name.lower(), plan.country.code.lower())
    companies = db.scalars(select(Company).where(
        Company.status.not_in(EXCLUDED),
        or_(func.lower(Company.headquarters_country).in_(names),
            exists().where(CompanyLocation.company_id == Company.id, func.lower(CompanyLocation.country).in_(names))),
    ).limit(LOCAL_SCAN_LIMIT)).all()
    facts = {cid: f for cid, f in load_facts(db, companies).items()
             if in_country(f, plan.country) and in_requested_area(f, plan.area, plan.country)
             and industry_fit(f.company, plan.profile) > 0}
    for rank, (f, score) in enumerate(ordered(facts, plan.profile, plan.area, plan.country)[:search.requested_count], 1):
        db.add(LeadSearchResult(search_id=search.id, company_id=f.company.id, rank=rank, relevance_score=score,
                                is_new=False))
        search.companies_found = rank
    return search.companies_found


def create_search(db: Session, user: User, data: LeadSearchCreate) -> LeadSearch:
    search = LeadSearch(**data.model_dump(), user_id=user.id)
    plan = plan_for(search)
    if plan.country:  # store the normalized place, not the spelling typed
        search.country = plan.country.name
        if plan.area and plan.area.kind == "governorate":
            search.region, search.city = plan.area.label, None
        elif plan.area and plan.area.kind == "city":
            search.city, search.region = plan.area.label, plan.area.region
    db.add(search)
    db.flush()
    audit_service.record(db, action=AuditAction.LEAD_SEARCH_CREATED, user_id=user.id, entity_type="lead_search",
                         entity_id=search.id)
    started = time.perf_counter()
    found = _local_results(db, search)
    db_lookup = round(time.perf_counter() - started, 3)
    search.progress = {"timings": {"db_lookup": db_lookup}}
    logger.info("search=%s db_lookup=%ss found=%s/%s", search.id, db_lookup, found, search.requested_count)
    if found >= search.requested_count:
        search.status, search.started_at = LeadSearchStatus.COMPLETED.value, func.now()
        search.completed_at = func.now()
    elif not connector_configs(plan.country):
        search.status, search.completed_at = LeadSearchStatus.PARTIAL.value, func.now()
        search.message = (f"Automatic discovery is not available for {search.country} yet; "
                          "showing the companies already in LeadFinder.")
    else:
        search.status, search.started_at = LeadSearchStatus.RESEARCHING.value, func.now()
        search.connectors_total = len(connector_configs(plan.country))
        jobs.enqueue(db, search)
    db.commit()
    db.refresh(search)
    if search.status == LeadSearchStatus.RESEARCHING:
        jobs.notify()
    return search


def research_status(db: Session, search_id: int) -> str | None:
    """Company research of the search's results: 'running' while any is queued / researching, 'completed'
    once some ran and none is pending, None when none was researched. Separate from the search's status."""
    statuses = set(db.scalars(select(Company.enrichment_status).distinct()
                              .join(LeadSearchResult, LeadSearchResult.company_id == Company.id)
                              .where(LeadSearchResult.search_id == search_id)))
    if statuses & {EnrichmentStatus.QUEUED.value, EnrichmentStatus.RESEARCHING.value}:
        return "running"
    return "completed" if statuses - {EnrichmentStatus.NOT_STARTED.value} else None


def get_search(db: Session, user: User, search_id: int) -> LeadSearch:
    """Agents see their own searches; managers and admins see everyone's (404 otherwise: no probing)."""
    search = db.get(LeadSearch, search_id)
    if search is None or not (permissions.is_privileged(user) or search.user_id == user.id):
        raise NotFoundError("Search not found")
    return search


def list_results(db: Session, user: User, search_id: int, params: PageParams):
    get_search(db, user, search_id)
    sources = (select(func.count(func.distinct(Evidence.source_id))).where(Evidence.company_id == Company.id)
               .correlate(Company).scalar_subquery())
    stmt = (select(LeadSearchResult, Company, sources)
            .join(Company, Company.id == LeadSearchResult.company_id)
            .where(LeadSearchResult.search_id == search_id)
            .order_by(LeadSearchResult.rank.nulls_last(), LeadSearchResult.id))
    total = db.scalar(select(func.count()).where(LeadSearchResult.search_id == search_id)) or 0
    rows = db.execute(stmt.limit(params.page_size).offset(params.offset)).all()
    items = [{"rank": r.rank, "relevance_score": r.relevance_score, "is_new": r.is_new, "company": c,
              "source_count": n} for r, c, n in rows]
    return items, total

