"""People research state machine: website research -> deep public-source research (queued automatically when the
website names no one) -> one final state the UI follows (completed / partial / failed / timed_out, zero people
included). Deadlines, the Common Crawl outage breaker, the watchdog (overdue and orphaned stages), worker restarts
and one active job per company and kind. Every page and API is mocked."""

from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.session import engine
from app.models import Company, ResearchRun, SourceLookup
from app.models.enums import UserRole
from app.services import jobs
from app.services.enrichment import orchestrator as enrichment
from app.services.people.external import orchestrator as external
from app.services.people.external.lebanon import commoncrawl, pack
from app.services.people.external.lebanon.records import Record
from app.services.people.orchestrator import research_state

from .test_external_people import web  # noqa: F401  (fixture)
from .test_lebanon_sources import keep, new_company

HOME = "<html><head><title>Omega Foods</title></head><body><h1>Omega Foods</h1><p>Bakery in Beirut.</p></body></html>"


def drain(*kinds: str) -> None:
    while jobs.run_next(kinds or (*jobs.RESEARCH, jobs.EXTERNAL)):
        pass


def research(client, company_id: int) -> dict:
    """The state as GET /companies/{id} returns it (opening a company also queues what is due)."""
    return client.get(f"/companies/{company_id}").json()["people_research"]


def state_of(db, company_id: int) -> dict:
    """The state the API reports, read without opening the company (nothing queued)."""
    db.expire_all()
    return research_state(db, db.get(Company, company_id))


def active_runs(db, company_id: int) -> dict[str, int]:
    db.expire_all()
    return dict(db.execute(select(ResearchRun.research_type, func.count()).where(
        ResearchRun.company_id == company_id, ResearchRun.status.in_(("queued", "running")))
        .group_by(ResearchRun.research_type)).all())


def omega(agent, web, **kw) -> int:
    web.sites["www.omegafoods.example"] = {"/": HOME}
    return new_company(agent, "Omega Foods", industry="Food Manufacturing", website="https://www.omegafoods.example",
                       **kw)


def test_website_zero_people_queues_deep_research_then_finishes_empty(client_for, db, web):
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = omega(agent, web)
    assert research(agent, company_id)["state"] == "website_queued"
    drain(*jobs.RESEARCH)  # company research, then website people: nobody on the site
    state = research(agent, company_id)
    assert state["state"] == "deep_queued" and state["website_status"] == "completed"
    assert active_runs(db, company_id) == {jobs.EXTERNAL: 1}  # queued automatically, not by the user
    drain(jobs.EXTERNAL)
    state = research(agent, company_id)
    assert state["state"] == "completed" and state["stage"] == "deep" and state["people_count"] == 0
    assert state["finished_at"] and "NO_EXTERNAL_PERSON_SOURCE" in state["gap_reasons"]
    assert active_runs(db, company_id) == {}  # nothing left to poll for


def test_unreadable_website_is_partial_and_deep_research_still_runs(client_for, db, web):
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = new_company(agent, "Omega Foods", industry="Food Manufacturing",
                             website="https://www.omegafoods.example")
    web.sites["www.omegafoods.example"] = {"/": httpx.ConnectError("refused")}
    agent.get(f"/companies/{company_id}")
    drain(*jobs.RESEARCH)
    company = db.get(Company, company_id)
    db.refresh(company)
    assert company.people_status == "partial"
    assert research(agent, company_id)["state"] == "deep_queued"  # a blocked website never stops research
    drain(jobs.EXTERNAL)
    assert research(agent, company_id)["state"] in ("completed", "partial")


def test_deep_research_finds_a_person_from_a_public_source(client_for, db, web):
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = omega(agent, web)
    keep(db, "berytech_profiles", "https://berytech.example/profiles/omega-foods",
         [Record(org=["Omega Foods"], person="Rana Saad", title="IT Manager", excerpt="Omega Foods: Rana Saad")])
    agent.get(f"/companies/{company_id}")
    drain()
    detail = agent.get(f"/companies/{company_id}").json()
    assert detail["people_research"]["state"] == "completed" and detail["people_research"]["people_count"] == 1
    assert [(p["person"]["full_name"], p["job_title"]) for p in detail["people"]] == [("Rana Saad", "IT Manager")]
    assert detail["people_research"]["gap_reasons"] == []


def test_deep_research_deadline_ends_as_timed_out(client_for, db, monkeypatch):
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = new_company(agent, "Omega Trading", industry="Distribution")
    monkeypatch.setattr(get_settings(), "external_job_seconds", 0)
    result = external.run(db, company_id, force=True)
    assert result["status"] == "timed_out" and result["stopped_deadline"]
    state = state_of(db, company_id)
    assert state["state"] == "timed_out" and state["message"] == jobs.TIMED_OUT_MESSAGE
    assert "SOURCE_FETCH_ERROR" in state["gap_reasons"]  # an incomplete attempt, said so


def test_common_crawl_outage_is_bounded_and_skipped_for_the_next_company(client_for, db, public_apis, monkeypatch):
    monkeypatch.setattr(commoncrawl.time, "sleep", lambda s: None)
    agent, _ = client_for(UserRole.SALES_AGENT)
    first = new_company(agent, "Omega Tech", industry="Technology", website="https://omegatech.example")
    second = new_company(agent, "Delta Tech", industry="Technology", website="https://deltatech.example")

    def hang(request):
        raise httpx.ReadTimeout("index too slow")  # a read timeout is retried; a refused connection is not

    public_apis.routes.update({
        ("index.commoncrawl.org", "/collinfo.json"): lambda r: httpx.Response(200, json=[{"id": "CC-MAIN-2026-39"}]),
        ("index.commoncrawl.org", "/CC-MAIN-2026-39-index"): hang})
    result = external.run(db, first, force=True)
    assert result["status"] in ("completed", "partial")  # finished: the archive's failure never hangs the company
    index_calls = [r for r in public_apis.requests if r.endswith("-index")]
    assert len(index_calls) == commoncrawl.RETRIES  # one host retried, then the archive is marked down
    assert not commoncrawl.available()
    assert {(l.status, l.failure_reason) for l in db.scalars(select(SourceLookup))} == {("failed", "NETWORK_ERROR")}
    assert "COMMON_CRAWL_ERROR" in state_of(db, first)["gap_reasons"]
    result = external.run(db, second, force=True)
    assert result["commoncrawl_unavailable"] == 1
    assert len([r for r in public_apis.requests if r.endswith("-index")]) == len(index_calls)  # not waited on again
    assert "SOURCE_FETCH_ERROR" in state_of(db, second)["gap_reasons"]
    monkeypatch.setattr(commoncrawl, "_down_until", [0.0])
    public_apis.routes[("index.commoncrawl.org", "/CC-MAIN-2026-39-index")] = lambda r: (_ for _ in ()).throw(
        httpx.ConnectError("refused"))
    external.run(db, new_company(agent, "Sigma Tech", industry="Technology", website="https://sigmatech.example"),
                 force=True)
    assert len([r for r in public_apis.requests if r.endswith("-index")]) == len(index_calls) + 1  # no retry
    assert not commoncrawl.available()


def test_watchdog_finishes_overdue_and_orphaned_stages(client_for, db):
    agent, _ = client_for(UserRole.SALES_AGENT)
    slow = new_company(agent, "Omega Trading", industry="Distribution")
    orphan = new_company(agent, "Delta Trading", industry="Distribution")
    run = ResearchRun(company_id=slow, research_type=jobs.EXTERNAL, status="running",
                      started_at=datetime.now(timezone.utc) - timedelta(hours=1))
    db.add(run)
    db.get(Company, slow).external_people_status = "researching"
    db.get(Company, orphan).people_status = "queued"  # no job behind it
    db.commit()
    with engine.connect() as worker:  # the overdue job's worker is still alive (holds the liveness lock)
        worker.execute(select(func.pg_advisory_lock(jobs._LIVENESS, run.id)))
        assert jobs.recover_interrupted(db) == 2
        worker.execute(select(func.pg_advisory_unlock(jobs._LIVENESS, run.id)))
        worker.commit()
    db.expire_all()
    assert db.get(ResearchRun, run.id).status == "failed"
    assert state_of(db, slow)["state"] == "timed_out"
    assert state_of(db, orphan)["state"] == "partial"


def test_worker_restart_finishes_the_interrupted_stage(client_for, db, web):
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = omega(agent, web)
    agent.get(f"/companies/{company_id}")
    drain(*jobs.RESEARCH)
    claimed = db.scalar(select(ResearchRun).where(ResearchRun.company_id == company_id,
                                                  ResearchRun.research_type == jobs.EXTERNAL))
    claimed.status, claimed.started_at = "running", datetime.now(timezone.utc)  # claimed, then the worker died
    db.get(Company, company_id).external_people_status = "researching"
    db.commit()
    assert research(agent, company_id)["state"] == "deep_researching"
    assert jobs.recover_interrupted(db) == 1  # the restarted worker's first recovery pass
    state = state_of(db, company_id)
    assert state["state"] == "partial" and "interrupted" in state["message"]


def test_one_active_job_per_company_and_kind(client_for, db, web):
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = omega(agent, web)
    for _ in range(10):
        agent.get(f"/companies/{company_id}")
        agent.get(f"/companies/{company_id}/people")
    assert active_runs(db, company_id) == {jobs.ENRICHMENT: 1}
    drain(*jobs.RESEARCH)
    company = db.get(Company, company_id)
    queued = db.scalar(select(ResearchRun).where(ResearchRun.company_id == company_id,
                                                 ResearchRun.research_type == jobs.EXTERNAL))
    queued.status = "running"  # a worker claimed it while a second open, reading the old state, asks again
    company.external_people_status = "completed"
    db.commit()
    external.request(db, company, enrichment.OPENED_NO_PEOPLE, force=True)
    db.commit()
    assert active_runs(db, company_id) == {jobs.EXTERNAL: 1}


def test_existing_people_stay_visible_while_research_refreshes(client_for, db, web):
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = omega(agent, web)
    keep(db, "berytech_profiles", "https://berytech.example/profiles/omega-foods",
         [Record(org=["Omega Foods"], person="Joseph Haddad", title="Chief Executive Officer", excerpt="Omega Foods")])
    pack.apply(db, db.get(Company, company_id))
    detail = agent.get(f"/companies/{company_id}").json()  # opening queues company research
    assert detail["people_research"]["state"] == "website_queued"
    assert [p["person"]["full_name"] for p in detail["people"]] == ["Joseph Haddad"]
