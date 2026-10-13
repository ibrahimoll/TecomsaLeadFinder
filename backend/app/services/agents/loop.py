"""The agents' loop, run as one thread of the worker (services/jobs.py). One process cluster-wide runs it (a pg
advisory lock), so scaling workers never doubles the model calls or the Scout's searches.

    Profiler  continuously: the next company to profile, one at a time (one GPU); idle 60 s when none or the
              model is down. Hourly: queue research for never-researched companies with a website.
    Scout     hourly: retrain on the sales statuses, rescore, maybe start a lookalike search.
"""

import logging
import threading
import time

from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.session import SessionLocal, engine
from app.services.agents import llm, profiler, scout

logger = logging.getLogger("leadfinder.agents")
_LOCK = 7_301_944  # advisory lock key: held by the one process running the agents
HOUR = 3600
IDLE_SECONDS = 60


def run(stop: threading.Event) -> None:
    with engine.connect() as lock:
        while not stop.is_set():  # another process runs the agents: try again later (it may stop)
            if lock.execute(select(func.pg_try_advisory_lock(_LOCK))).scalar():
                lock.commit()
                break
            lock.commit()
            stop.wait(HOUR / 6)
        logger.info("agents started (model %s)", get_settings().ollama_model)
        fed_at = scouted_at = 0.0
        while not stop.is_set():
            try:
                now = time.monotonic()
                if now - scouted_at > HOUR:
                    scouted_at = now
                    from app.services import odoo_crm

                    if odoo_crm.configured():  # first: won / lost deals in Odoo are what the Scout learns from
                        try:
                            with SessionLocal() as db:
                                odoo_crm.sync(db)
                        except Exception:  # Odoo down or refusing: retried next hour, the agents carry on
                            logger.exception("odoo sync failed")
                    with SessionLocal() as db:
                        scout.run(db)
                if now - fed_at > HOUR:
                    fed_at = now
                    with SessionLocal() as db:
                        if queued := profiler.feed(db):
                            logger.info("profiler queued research for %s companies", queued)
                if not llm.available():
                    stop.wait(IDLE_SECONDS)
                    continue
                with SessionLocal() as db:
                    company = profiler.next_company(db)
                    outcome = profiler.profile(db, company) if company else None
                if outcome in (None, "model_down"):
                    stop.wait(IDLE_SECONDS)
            except Exception:  # database or model hiccup: keep the agents alive
                logger.exception("agents loop error")
                stop.wait(IDLE_SECONDS)


def start(stop: threading.Event) -> threading.Thread | None:
    if not get_settings().agents_enabled:
        return None
    thread = threading.Thread(target=run, args=(stop,), name="agents", daemon=True)
    thread.start()
    return thread
