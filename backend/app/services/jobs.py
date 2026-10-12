"""Background jobs on PostgreSQL: the `research_runs` table is the queue (no Redis, no extra service).

* enqueue(): a queued research_runs row plus a pg_notify, committed with the caller's transaction, so a job is
  never lost and an idle worker wakes up at once (LISTEN), in this process or another.
* claim: `UPDATE ... WHERE id = (SELECT ... FOR UPDATE SKIP LOCKED)`: any number of workers / processes
  can poll, each job runs exactly once.
* Liveness: the worker running a job holds a pg advisory lock (_LIVENESS, run id) for as long as it runs. A
  "running" job whose lock nobody holds belongs to a process that stopped: it is failed right away
  (recover_interrupted), so a restart never leaves a search "researching" forever.
* Deadlines: a research job still running past its hard limit (deadline_seconds) has its company stage finished
  as timed_out by the watchdog (the job's own budgets normally stop it first); a company left queued /
  researching without any active job (an orphan) is finished too. The UI never polls a stage that cannot end.
* One active job per company and kind (unique index on queued + running): opening a company ten times while it is
  researched queues nothing more.
* Lanes: discovery jobs (DISCOVERY_WORKER_THREADS at a time) and research jobs - company research and people
  discovery (ENRICHMENT_WORKER_THREADS at a time) - never wait for each other: a slow website never delays the
  next user's search.
* Priority: lower `priority` runs first (enrichment: the company a user has open before search results).

Development runs the worker as its own process (docker compose service `worker`): python -m app.services.jobs
With DISCOVERY_WORKER_ENABLED=true the same lanes run inside the API process instead.
"""

import contextvars
import logging
import threading
import time
from datetime import datetime, timezone

import psycopg
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal, engine
from app.models import LeadSearch, ResearchRun
from app.models.enums import LeadSearchStatus, ResearchRunStatus

logger = logging.getLogger("leadfinder.jobs")
DISCOVERY = "company_discovery"
ENRICHMENT = "company_enrichment"
PEOPLE = "people_discovery"
EXTERNAL = "external_people"
CONTACT = "contact_discovery"
RESEARCH = (ENRICHMENT, PEOPLE, CONTACT)  # research lanes (contact research is short and bounded)
CHANNEL = "leadfinder_jobs"
POLL_SECONDS = 5  # fallback poll when a notification is missed (e.g. the listener reconnecting)
RECOVERY_SECONDS = 60
ACTIVE = "status IN ('queued', 'running') AND company_id IS NOT NULL"  # the unique index's predicate
GRACE_SECONDS = 60  # beyond a stage's own time budget before the watchdog finishes it
_LIVENESS = 7_301_943  # advisory lock namespace: (_LIVENESS, run id) is held by the worker running that job

pipeline: contextvars.ContextVar[int | None] = contextvars.ContextVar("pipeline", default=None)
_stop = threading.Event()
_lanes: list[threading.Event] = []
_threads: list[threading.Thread] = []


def enqueue(db: Session, search: LeadSearch) -> ResearchRun:
    """Adds the discovery job (and its wake-up notification, delivered on commit) to the caller's transaction."""
    run = ResearchRun(search_id=search.id, research_type=DISCOVERY, status=ResearchRunStatus.QUEUED.value,
                      requested_by_user_id=search.user_id)
    db.add(run)
    wake(db, DISCOVERY)
    return run


def wake(db: Session, kind: str) -> None:
    """Wakes idle workers in every process once the caller's transaction commits."""
    db.execute(select(func.pg_notify(CHANNEL, kind)))


def chained() -> dict:
    """Metadata of a job queued by the running one: the same pipeline id (logs follow one company's research)."""
    return {"pipeline": pipeline.get()} if pipeline.get() else {}


def deadline_seconds(kind: str) -> float:
    s = get_settings()
    return {EXTERNAL: s.external_job_seconds, CONTACT: s.contact_job_seconds}.get(
        kind, s.enrichment_job_seconds) + GRACE_SECONDS


def notify() -> None:
    """Wakes this process's lanes (other processes are woken by the pg_notify sent with the job)."""
    for lane in _lanes:
        lane.set()


_CLAIM = text(
    "UPDATE research_runs SET status = 'running', started_at = now() WHERE id = ("
    " SELECT id FROM research_runs WHERE status = 'queued' AND research_type = ANY(:kinds)"
    " ORDER BY priority, created_at, id FOR UPDATE SKIP LOCKED LIMIT 1)"
    " RETURNING id, extract(epoch FROM now() - created_at)")


def run_next(kinds: tuple[str, ...] = (DISCOVERY, *RESEARCH, EXTERNAL)) -> bool:
    """Runs one queued job of these kinds, if any. Returns whether there was one."""
    with engine.connect() as lock:  # claimed and locked in one transaction: never "running" without an owner
        claimed = lock.execute(_CLAIM, {"kinds": list(kinds)}).first()
        if claimed is None:
            lock.commit()
            return False
        run_id, waited = claimed
        lock.execute(select(func.pg_advisory_lock(_LIVENESS, run_id)))
        lock.commit()
        try:
            _run(run_id, float(waited or 0))
        finally:
            lock.execute(select(func.pg_advisory_unlock(_LIVENESS, run_id)))
            lock.commit()
    return True


def _run(run_id: int, queue_wait: float) -> None:
    from app.services.discovery import orchestrator  # heavy imports only when a job actually runs
    from app.services.enrichment import orchestrator as enrichment
    from app.services.people import orchestrator as people
    from app.services.people.external import orchestrator as external
    from app.services import contact_intelligence as contacts

    with SessionLocal() as db:
        run = db.get(ResearchRun, run_id)
        search = db.get(LeadSearch, run.search_id) if run.search_id else None
        kind = run.research_type  # read now: after a failed flush the instance cannot be loaded again
        research = kind in (*RESEARCH, EXTERNAL)
        force, priority = bool((run.metadata_ or {}).get("force")), run.priority
        company_id, started = run.company_id, time.perf_counter()
        token = pipeline.set((run.metadata_ or {}).get("pipeline") or run_id)
        if research:
            logger.info("company=%s pipeline=%s job=%s stage=%s status=queued->running queue_wait=%.2f",
                        company_id, pipeline.get(), run_id, kind, queue_wait)
        try:
            if research:
                if kind == EXTERNAL:
                    result = external.run(db, run.company_id, force=force, queue_wait=queue_wait)
                elif kind == CONTACT:
                    result = contacts.run(db, run.company_id, force=force, queue_wait=queue_wait)
                elif kind == PEOPLE:
                    result = people.run(db, run.company_id, force=force, queue_wait=queue_wait, priority=priority)
                else:
                    result = enrichment.run(db, run.company_id, force=force, queue_wait=queue_wait,
                                            priority=priority)
                run = db.get(ResearchRun, run_id)
                run.status = {"completed": ResearchRunStatus.COMPLETED, "partial": ResearchRunStatus.PARTIAL,
                              "timed_out": ResearchRunStatus.PARTIAL}.get(
                    result.get("status"), ResearchRunStatus.COMPLETED).value
                run.metadata_ = {**(run.metadata_ or {}), "result": result}
            elif search is None:
                raise LookupError("the search was deleted")
            else:
                orchestrator.run(db, search, queue_wait=queue_wait)
                run.status = {LeadSearchStatus.COMPLETED: ResearchRunStatus.COMPLETED,
                              LeadSearchStatus.PARTIAL: ResearchRunStatus.PARTIAL}.get(
                    search.status, ResearchRunStatus.FAILED).value
                run.metadata_ = search.progress
        except Exception as exc:
            logger.exception("Job %s (%s) failed", run_id, kind)
            db.rollback()
            run = db.get(ResearchRun, run_id)
            run.status, run.error_message = ResearchRunStatus.FAILED.value, f"{exc.__class__.__name__}: {exc}"[:2000]
            if research:
                _stop_research(db, kind, run.company_id, "Research stopped unexpectedly.", failed=True)
            elif search is not None:
                _stop_search(db, run.search_id, "Discovery stopped unexpectedly. The companies found so far are kept.")
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
        if research:
            elapsed = time.perf_counter() - started
            logger.info("company=%s pipeline=%s job=%s stage=%s status=running->%s people=%s execution=%.2f "
                        "queue_wait=%.2f total=%.2f", company_id, pipeline.get(), run_id, kind, run.status,
                        ((run.metadata_ or {}).get("result") or {}).get("coverage", {}).get("people"), elapsed,
                        queue_wait, elapsed + queue_wait)
        pipeline.reset(token)


def _stop_search(db: Session, search_id: int | None, message: str) -> None:
    """A discovery that ended abnormally keeps what it found: partial (or failed when it found nothing)."""
    search = db.get(LeadSearch, search_id) if search_id else None
    if search is not None and search.status == LeadSearchStatus.RESEARCHING.value:
        search.status = (LeadSearchStatus.PARTIAL if search.companies_found else LeadSearchStatus.FAILED).value
        search.message, search.completed_at = message, datetime.now(timezone.utc)


_PREFIX = {PEOPLE: "people", EXTERNAL: "external_people", ENRICHMENT: "enrichment", CONTACT: "contact"}
_FINISHED_AT = {PEOPLE: "people_researched_at", EXTERNAL: "external_people_researched_at",
                ENRICHMENT: "enrichment_completed_at", CONTACT: "contact_researched_at"}
TIMED_OUT_MESSAGE = "Research reached its time limit. Existing verified results are shown."


def _stop_research(db: Session, kind: str, company_id: int | None, message: str, failed: bool = False,
                   status: str | None = None) -> None:
    from app.models import Company
    from app.models.enums import EnrichmentStatus

    company = db.get(Company, company_id) if company_id else None
    prefix = _PREFIX.get(kind, "enrichment")
    if company is not None and getattr(company, f"{prefix}_status") in (EnrichmentStatus.QUEUED,
                                                                         EnrichmentStatus.RESEARCHING):
        setattr(company, f"{prefix}_status",
                status or (EnrichmentStatus.FAILED if failed else EnrichmentStatus.PARTIAL).value)
        setattr(company, f"{prefix}_message", message)
        setattr(company, _FINISHED_AT.get(kind, "enrichment_completed_at"), datetime.now(timezone.utc))


def recover_interrupted(db: Session) -> int:
    """Fail the jobs marked running whose worker is gone (their liveness lock is free), and their searches."""
    dead = []
    for run in db.scalars(select(ResearchRun).where(ResearchRun.status == ResearchRunStatus.RUNNING.value)):
        if db.scalar(select(func.pg_try_advisory_lock(_LIVENESS, run.id))):
            db.scalar(select(func.pg_advisory_unlock(_LIVENESS, run.id)))
            dead.append(run)
    for run in dead:
        run.status, run.error_message = ResearchRunStatus.FAILED.value, "Interrupted (the worker stopped)."
        run.completed_at = datetime.now(timezone.utc)
        if run.research_type in (*RESEARCH, EXTERNAL):
            _stop_research(db, run.research_type, run.company_id, "Research was interrupted; it can be refreshed.")
        elif run.research_type == DISCOVERY:
            _stop_search(db, run.search_id, "Discovery was interrupted. The companies found so far are kept.")
    db.commit()
    return len(dead) + finish_overdue(db)


def finish_overdue(db: Session) -> int:
    """The watchdog. A research job still running past its hard limit: its company stage is finished as timed_out
    (the job is marked failed and stops blocking a new request; if its thread ends later it records its result).
    A company stage left queued / researching with no active job of its kind (an orphan): finished as partial."""
    from app.models.enums import EnrichmentStatus

    count = 0
    for kind in (*RESEARCH, EXTERNAL):
        overdue = db.scalars(select(ResearchRun).where(
            ResearchRun.status == ResearchRunStatus.RUNNING.value, ResearchRun.research_type == kind,
            ResearchRun.started_at < func.now() - text(f"interval '{int(deadline_seconds(kind))} seconds'"))).all()
        for run in overdue:
            logger.warning("company=%s pipeline=%s job=%s stage=%s status=running->timed_out (watchdog)",
                           run.company_id, (run.metadata_ or {}).get("pipeline") or run.id, run.id, kind)
            run.status, run.error_message = ResearchRunStatus.FAILED.value, "Timed out (watchdog)."
            run.completed_at = datetime.now(timezone.utc)
            _stop_research(db, kind, run.company_id, TIMED_OUT_MESSAGE, status=EnrichmentStatus.TIMED_OUT.value)
        db.flush()
        prefix = _PREFIX[kind]
        orphans = db.execute(text(
            f"UPDATE companies c SET {prefix}_status = 'partial', {_FINISHED_AT[kind]} = now(), "
            f"{prefix}_message = 'Research was interrupted; it can be refreshed.' "
            f"WHERE {prefix}_status IN ('queued', 'researching') AND NOT EXISTS (SELECT 1 FROM research_runs r "
            f"WHERE r.company_id = c.id AND r.research_type = :k AND r.status IN ('queued', 'running')) "
            f"RETURNING c.id"), {"k": kind}).scalars().all()
        if orphans:
            logger.warning("stage=%s finished %s orphaned company state(s): %s", kind, len(orphans), orphans[:20])
        count += len(overdue) + len(orphans)
    db.commit()
    return count


def _lane(kinds: tuple[str, ...], wake: threading.Event) -> None:
    while not _stop.is_set():
        wake.clear()  # cleared before looking: a job queued meanwhile wakes the wait below at once
        try:
            if run_next(kinds):
                continue
        except Exception:  # the database is briefly unavailable, etc.: keep the worker alive
            logger.exception("Job worker error")
        wake.wait(POLL_SECONDS)


def _listen() -> None:
    """LISTEN for new jobs (from any process) and periodically fail jobs whose worker died."""
    url = make_url(get_settings().database_url).set(drivername="postgresql").render_as_string(hide_password=False)
    recovered_at = 0.0
    while not _stop.is_set():
        try:
            with psycopg.connect(url, autocommit=True) as conn:
                conn.execute(f"LISTEN {CHANNEL}")
                notify()  # anything queued while not listening
                while not _stop.is_set():
                    if time.monotonic() - recovered_at > RECOVERY_SECONDS:
                        recovered_at = time.monotonic()
                        with SessionLocal() as db:
                            if count := recover_interrupted(db):
                                logger.warning("Failed %s interrupted job(s)", count)
                    for _ in conn.notifies(timeout=POLL_SECONDS, stop_after=1):
                        notify()
        except Exception:
            logger.exception("Job listener error; reconnecting")
            _stop.wait(POLL_SECONDS)


def start_worker() -> None:
    if any(t.is_alive() for t in _threads):
        return
    _stop.clear()
    _lanes.clear()
    _threads.clear()
    settings = get_settings()
    lanes = ([(DISCOVERY,)] * settings.discovery_worker_threads + [RESEARCH] * settings.enrichment_worker_threads
             + [(EXTERNAL,)] * settings.external_people_worker_threads)
    for i, kinds in enumerate(lanes):
        _lanes.append(wake := threading.Event())
        _threads.append(threading.Thread(target=_lane, args=(kinds, wake), name=f"job-{kinds[0]}-{i}", daemon=True))
    _threads.append(threading.Thread(target=_listen, name="job-listener", daemon=True))
    for t in _threads:
        t.start()
    logger.info("Job worker started: %s discovery lane(s), %s research lane(s), %s external people lane(s)",
                settings.discovery_worker_threads, settings.enrichment_worker_threads,
                settings.external_people_worker_threads)


def stop_worker() -> None:
    _stop.set()
    notify()


if __name__ == "__main__":
    import signal

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for sig in (signal.SIGTERM, signal.SIGINT):  # docker stop / watchfiles reload: stop cleanly
        signal.signal(sig, lambda *_: stop_worker())
    start_worker()
    from app.services.agents import loop as agents  # the Profiler and the Scout (one process cluster-wide)

    agents.start(_stop)
    purged_at = 0.0
    while not _stop.wait(1):
        if time.monotonic() - purged_at > 86400:  # contact retention, daily (idempotent: any worker may run it)
            purged_at = time.monotonic()
            try:
                from app.services.privacy import purge_expired

                with SessionLocal() as db:
                    purge_expired(db)
            except Exception:
                logger.exception("retention purge failed (retried tomorrow)")
