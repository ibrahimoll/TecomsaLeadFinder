"""Discovery orchestrator: runs one lead search's discovery job (in the job worker, never in a request).

    Search (already holds the companies LeadFinder knew, see search_service)
      -> connectors, concurrently (bounded), each within a deadline; one failing never stops the others
      -> CompanyCandidates -> validate -> consolidate (branches / duplicate listings) -> normalize
      -> resolve against the master database (deduplication) -> persist company + sources + evidence
      -> search results (progressively, committed company by company)
      -> ranking and status: completed, partial (fewer trustworthy companies than requested), failed
    then: company research (services/enrichment) is queued for the results with a website: their own jobs,
    which never hold the search's status back.

Only the missing number of companies is created. Once the search is full, the next `limit` groups of each
source are still matched, to confirm companies already in the results (extra sources / evidence / locations),
never to add more; lower-ranked listings are left alone (the database loop is the expensive part).
Timings per stage are logged by search id and kept in search.progress["timings"] (managers / admins).
"""

import copy
import logging
import math
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Company, LeadSearch, LeadSearchResult
from app.models.enums import IdentityConfidence, LeadSearchStatus
from app.services import jobs
from app.services.discovery import connectors as connector_registry
from app.services.discovery.candidate import Connector, ConnectorConfig, ConnectorError, ConnectorResult, SearchQuery
from app.services.discovery.config import load_configs
from app.services.discovery.consolidation import assess, consolidate
from app.services.discovery.deduplication import resolve
from app.services.discovery.geography import Area, Country, find_area, find_country
from app.services.discovery.industries import profile_for
from app.services.discovery.normalizer import normalize, validate
from app.services.discovery.persistence import save
from app.services.discovery.ranking import load_facts, ordered

logger = logging.getLogger("leadfinder.discovery")

BUFFER = 0.25  # look for 25% more than the deficit: some candidates turn out to be duplicates
_LOCK_KEY = 7_301_942  # pg advisory lock: one resolve-and-create at a time (no duplicate companies under races)
MAX_PARALLEL_CONNECTORS = 4
# While a higher-priority source is still answering, results are taken in priority order for at most this
# long; after that, whatever is ready goes first.
PRIORITY_GRACE_SECONDS = 2.0
MAX_GROUPS_PER_LIMIT = 10  # never match more than 10 x limit groups of one source against the database
# ponytail: only a source's best-scored candidates are consolidated (branches further down are matched by
# deduplication instead); raise it if chains with hundreds of low-scored branches show up as duplicates.
CONSOLIDATE_PER_LIMIT, CONSOLIDATE_MIN = 40, 2000


@dataclass
class Plan:
    country: Country | None
    area: Area | None
    profile: object


def plan_for(search: LeadSearch) -> Plan:
    country = find_country(search.country)
    area = find_area(country.code, search.city or search.region) if country else None
    return Plan(country, area, profile_for(search.industry))


def connector_configs(country: Country | None) -> list[ConnectorConfig]:
    if country is None:
        return []
    return [c for c in load_configs() if c.enabled and c.supports(country.code)]


def build_connectors(country: Country | None) -> list[Connector]:
    """Replaced in tests with fake connectors."""
    built = []
    for config in connector_configs(country):
        try:
            built.append(connector_registry.build(config))
        except Exception:  # a misconfigured connector is skipped, never fatal
            logger.exception("Connector %s is misconfigured and was skipped", config.key)
    return built


def _result_ids(db: Session, search: LeadSearch) -> set[int]:
    return set(db.scalars(select(LeadSearchResult.company_id).where(LeadSearchResult.search_id == search.id)))


def _too_weak(group, norms, assessment) -> bool:
    """A new company needs more than a name and a map pin: low-confidence records are only created when the
    business can be identified and reached (its own website or a phone number)."""
    if assessment.confidence != IdentityConfidence.LOW:
        return False
    return not any(norms[id(c)].domain or norms[id(c)].phone for c in group.records)


class Clock:
    """Seconds spent per stage of one search (summed over sources)."""

    def __init__(self):
        self.started, self.stages = time.perf_counter(), Counter()
        self.first_result: float | None = None

    def lap(self, stage: str, since: float) -> float:
        now = time.perf_counter()
        self.stages[stage] += now - since
        return now

    def result_added(self) -> None:
        if self.first_result is None:
            self.first_result = time.perf_counter() - self.started


def _process(db: Session, search: LeadSearch, plan: Plan, config: ConnectorConfig, result: ConnectorResult,
             configs: dict[str, ConnectorConfig], limit: int, clock: Clock) -> dict:
    t = time.perf_counter()
    rejected: Counter[str] = Counter()
    accepted = []
    for c in result.candidates:
        validate(c)
        if c.rejected:
            rejected[c.rejected] += 1
        else:
            accepted.append(c)
    t = clock.lap("validate", t)
    window = accepted[:max(CONSOLIDATE_MIN, limit * CONSOLIDATE_PER_LIMIT)]
    groups = consolidate(window)
    t = clock.lap("consolidate", t)
    stats = Counter(discovered=len(result.candidates), accepted=len(accepted), groups=len(groups),
                    branches_merged=len(window) - len(groups))
    norms: dict = {}
    in_results = _result_ids(db, search)
    confirming = 0
    for i, group in enumerate(groups):
        full = search.companies_found >= search.requested_count
        confirming += full
        if confirming > limit or i >= limit * MAX_GROUPS_PER_LIMIT:
            stats["not_matched"] = len(groups) - i  # lower-ranked listings: not needed for this search
            break
        for c in group.records:  # only the groups actually used are normalized
            if id(c) not in norms:
                norms[id(c)] = normalize(c, plan.country, plan.profile)
        t = clock.lap("normalize", t)
        db.execute(select(func.pg_advisory_xact_lock(_LOCK_KEY)))
        resolution = resolve(db, group, norms, plan.country.code)
        t = clock.lap("deduplicate", t)
        if resolution.suppressed:
            stats["suppressed"] += 1
            db.rollback()
            continue
        known = resolution.company is not None
        if full and not (known and resolution.company.id in in_results):
            db.rollback()  # the search is full: only confirm companies it already returned
            continue
        assessment = assess(group)
        if not known and _too_weak(group, norms, assessment):
            stats["low_confidence"] += 1  # never fill a search with junk
            db.rollback()
            continue
        t = time.perf_counter()
        company, is_new = save(db, group=group, norms=norms, resolution=resolution, assessment=assessment,
                               country=plan.country, configs=configs, versions={config.key: result.version},
                               user_id=search.user_id)
        stats["created" if is_new else "reused"] += 1
        stats["possible_duplicates"] += len(resolution.possible)
        if company.id not in in_results:
            search.companies_found += 1
            db.add(LeadSearchResult(search_id=search.id, company_id=company.id, rank=search.companies_found,
                                    is_new=is_new))
            in_results.add(company.id)
            clock.result_added()
        db.commit()  # each company is visible to the user as soon as it is saved (and the lock is released)
        t = clock.lap("persist", t)
    stats.update({f"rejected_{k.lower()}": v for k, v in rejected.items()})
    return dict(stats)


def rerank(db: Session, search: LeadSearch, plan: Plan) -> None:
    results = {r.company_id: r for r in db.scalars(select(LeadSearchResult)
                                                   .where(LeadSearchResult.search_id == search.id)).all()}
    companies = db.scalars(select(Company).where(Company.id.in_(list(results)))).all() if results else []
    for rank, (facts, score) in enumerate(ordered(load_facts(db, companies), plan.profile, plan.area, plan.country), 1):
        results[facts.company.id].rank, results[facts.company.id].relevance_score = rank, score


def queue_research(db: Session, search: LeadSearch) -> int:
    """Company research for the search's results that have a website and no fresh research (the caller
    commits). Results stay visible and the search final while it runs."""
    from app.services.enrichment import orchestrator as enrichment

    companies = db.scalars(select(Company).join(LeadSearchResult, LeadSearchResult.company_id == Company.id)
                           .where(LeadSearchResult.search_id == search.id, Company.website.is_not(None))).all()
    return sum(enrichment.request(db, c, enrichment.SEARCH, user_id=search.user_id, search_id=search.id)
               for c in companies)


def _search(connector: Connector, query: SearchQuery) -> tuple[ConnectorResult, float]:
    started = time.perf_counter()
    return connector.search_companies(query), time.perf_counter() - started


def _outcomes(connectors: list[Connector], query: SearchQuery, deadline: float):
    """Runs the connectors concurrently and yields (connector, result or exception, seconds) as they finish:
    in priority order while a higher-priority source is still running (for PRIORITY_GRACE_SECONDS), then as
    ready. A source still running at the deadline is reported as timed out; its thread finishes in the
    background (e.g. a first download that fills the cache for the next search)."""
    if not connectors:
        return
    pool = ThreadPoolExecutor(min(len(connectors), MAX_PARALLEL_CONNECTORS), thread_name_prefix="connector")
    started = time.monotonic()
    pending = [(c, pool.submit(_search, c, query)) for c in connectors]
    try:
        while pending:
            elapsed = time.monotonic() - started
            ready = next((p for p in pending if p[1].done()), None)
            if ready is not None and (ready is pending[0] or elapsed >= PRIORITY_GRACE_SECONDS):
                pending.remove(ready)
                try:
                    result, seconds = ready[1].result()
                except Exception as exc:
                    yield ready[0], exc, elapsed
                else:
                    yield ready[0], result, seconds
                continue
            if elapsed >= deadline:
                for connector, _ in pending:
                    yield connector, ConnectorError(f"No answer within {deadline:.0f} seconds."), elapsed
                return
            if elapsed < PRIORITY_GRACE_SECONDS:  # briefly wait for the best source still running
                wait([pending[0][1]], timeout=min(PRIORITY_GRACE_SECONDS, deadline) - elapsed)
            else:
                wait([f for _, f in pending], timeout=deadline - elapsed, return_when=FIRST_COMPLETED)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def run(db: Session, search: LeadSearch, connectors: list[Connector] | None = None,
        queue_wait: float | None = None) -> None:
    clock = Clock()
    settings = get_settings()
    plan = plan_for(search)
    connectors = build_connectors(plan.country) if connectors is None else connectors
    configs = {c.config.key: c.config for c in connectors}
    deficit = max(0, search.requested_count - search.companies_found)
    limit = deficit + max(5, math.ceil(deficit * BUFFER))
    query = SearchQuery(plan.country, plan.area, plan.profile, limit=limit, region_text=search.region,
                        city_text=search.city)
    search.status, search.connectors_total = LeadSearchStatus.RESEARCHING.value, len(connectors)
    search.started_at = search.started_at or datetime.now(timezone.utc)
    timings = dict((search.progress or {}).get("timings", {}))  # db_lookup, measured by the request
    if queue_wait is not None:
        timings["queue_wait"] = round(queue_wait, 2)
    progress: dict = {"connectors": {}, "timings": timings}
    search.progress = copy.deepcopy(progress)
    db.commit()
    failures = 0
    for connector, outcome, seconds in _outcomes(connectors, query, settings.discovery_connector_timeout_seconds):
        config = connector.config
        stats: dict = {"label": config.label, "seconds": round(seconds, 2)}
        if isinstance(outcome, Exception):
            failures += 1
            if isinstance(outcome, ConnectorError):
                stats |= {"status": "failed", "error": str(outcome)}
            else:
                logger.error("search=%s connector=%s crashed", search.id, config.key, exc_info=outcome)
                stats |= {"status": "failed", "error": "Unexpected error (details in the server log)."}
        else:
            stats |= {"status": "completed", "dataset": outcome.version, "scanned": outcome.scanned}
            started = time.perf_counter()
            try:
                stats |= _process(db, search, plan, config, outcome, configs, limit, clock)
            except Exception:
                db.rollback()
                failures += 1
                logger.exception("search=%s connector=%s crashed", search.id, config.key)
                stats |= {"status": "failed", "error": "Unexpected error (details in the server log)."}
            stats["processing_seconds"] = round(time.perf_counter() - started, 2)
        progress["connectors"][config.key] = stats
        search.connectors_completed += 1
        search.progress = copy.deepcopy(progress)  # nested dicts too: JSONB is compared, not change-tracked
        db.commit()
        logger.info("search=%s connector=%s status=%s seconds=%s processing=%s discovered=%s accepted=%s created=%s "
                    "reused=%s not_matched=%s rejected=%s error=%s", search.id, config.key, stats.get("status"),
                    stats["seconds"], stats.get("processing_seconds"), stats.get("discovered", 0),
                    stats.get("accepted", 0), stats.get("created", 0), stats.get("reused", 0),
                    stats.get("not_matched", 0), {k: v for k, v in stats.items() if k.startswith("rejected_")},
                    stats.get("error"))

    t = time.perf_counter()
    rerank(db, search, plan)
    clock.lap("rank", t)
    found, wanted = search.companies_found, search.requested_count
    if found >= wanted:
        search.status, search.message = LeadSearchStatus.COMPLETED.value, None
    elif connectors and failures == len(connectors) and found == 0:
        search.status, search.message = LeadSearchStatus.FAILED.value, "The discovery sources could not be reached. Try again later."
    else:
        search.status = LeadSearchStatus.PARTIAL.value
        search.message = (f"Only {found} trustworthy {'company matches' if found == 1 else 'companies match'} this "
                          f"search so far." + (" Some sources were unavailable." if failures else ""))
    timings |= {stage: round(v, 3) for stage, v in clock.stages.items()}
    timings |= {"first_result": round(clock.first_result, 2) if clock.first_result is not None else None,
                "discovery_total": round(time.perf_counter() - clock.started, 2)}
    progress["timings"] = timings
    progress["research_queued"] = queue_research(db, search)  # enrichment: own jobs, once the status is final
    search.progress = copy.deepcopy(progress)
    search.completed_at = datetime.now(timezone.utc)
    db.commit()
    jobs.notify()
    logger.info("search=%s finished status=%s found=%s/%s timings=%s", search.id, search.status, found, wanted,
                timings)
