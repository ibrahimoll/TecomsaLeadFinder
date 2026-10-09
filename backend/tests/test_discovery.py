"""Find Leads discovery: database first, deficit-only discovery, normalization, entity resolution,
provenance, idempotency, incremental growth, failure isolation, statuses. Fake connectors, mocked web."""

import threading
import time

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.session import engine
from app.models import (Company, CompanyIdentifier, CompanyLocation, Evidence, LeadSearch, LeadSearchResult, Phone,
                        PossibleDuplicate, ResearchRun, Source)
from app.models.enums import UserRole
from app.services import jobs
from app.services.discovery import fetch, orchestrator
from app.services.enrichment import orchestrator as enrichment
from app.services.discovery.candidate import (CompanyCandidate, ConnectorConfig, ConnectorError, ConnectorResult,
                                              SearchQuery)
from app.services.discovery.web import PoliteFetcher

BEIRUT = (33.8938, 35.5018)
FOOD = {"industry": "Manufacturer", "categories": ["manufacturer", "food_manufacturer"], "tier": "category"}


def config(key: str, quality: int = 60, source_type: str = "open_dataset", priority: int = 20) -> ConnectorConfig:
    return ConnectorConfig(key=key, kind="dataset_file", enabled=True, countries=("LB",), priority=priority,
                           source_type=source_type, quality=quality, label=key.title())


def cand(name: str, connector: str = "gov", n: int = 0, **kw) -> CompanyCandidate:
    """A Beirut food manufacturer with a phone (enough evidence to be created)."""
    lat, lon = kw.pop("at", (BEIRUT[0] + n * 0.002, BEIRUT[1] + n * 0.002))
    values = {**FOOD, "external_id": f"{connector}-{name}", "phone": f"+961 1 {200000 + n}", "city": "Beirut",
              "address": f"Street {n}", **kw}
    return CompanyCandidate(connector=connector, source_name=f"{connector} source", source_type="open_dataset",
                            company_name=name, latitude=lat, longitude=lon, **values)


class FakeConnector:
    def __init__(self, cfg: ConnectorConfig, make=None, error: Exception | None = None):
        self.config, self.make, self.error, self.calls = cfg, make or (lambda: []), error, 0

    def search_companies(self, query: SearchQuery) -> ConnectorResult:
        self.calls += 1
        if self.error:
            raise self.error
        candidates = self.make()
        for c in candidates:  # like a real connector: the source type comes from its configuration
            c.source_type = self.config.source_type
        return ConnectorResult(candidates=candidates, version="test", scanned=len(candidates))


@pytest.fixture
def sources(monkeypatch):
    """sources(connector, ...) installs the connectors the next discovery jobs will use."""
    installed: list[FakeConnector] = []
    monkeypatch.setattr(orchestrator, "build_connectors", lambda country: list(installed))

    def install(*connectors):
        installed[:] = connectors
        return connectors
    return install


@pytest.fixture
def web(monkeypatch):
    """Company websites served from a dict {host: html}; anything else is a 404."""
    pages: dict[str, str] = {}
    monkeypatch.setattr(fetch, "resolve", lambda host: ["93.184.216.34"])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        body = pages.get(request.url.host)
        return httpx.Response(200, text=body, headers={"content-type": "text/html"}) if body else httpx.Response(404)

    monkeypatch.setattr(enrichment, "website_fetcher", lambda: PoliteFetcher(
        fetch.Fetcher(max_bytes=100_000, timeout=5, transport=httpx.MockTransport(handler)), min_interval=0,
        retries=0))
    return pages


def search(client, count: int = 5, **kw) -> dict:
    payload = {"country": "Lebanon", "city": "Beirut", "industry": "Food Manufacturing", "solution": "odoo",
               "requested_count": count, **kw}
    response = client.post("/lead-searches", json=payload)
    assert response.status_code == 201, response.text
    while jobs.run_next():  # the worker, synchronously
        pass
    return client.get(f"/lead-searches/{response.json()['id']}").json()


def results(client, search_id: int) -> list[dict]:
    return client.get(f"/lead-searches/{search_id}/results", params={"page_size": 100}).json()["items"]


def count(db, model) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(model))


# ---- 1-3: search finds NEW companies; the ones LeadFinder has are counted, never returned ---------------------


def test_known_companies_are_counted_not_returned(client_for, db, sources):
    agent, _ = client_for(UserRole.SALES_AGENT)
    for name in ("Alpha Foods", "Beta Foods", "Gamma Foods"):
        agent.post("/companies", json={"name": name, "industry": "Food Manufacturing", "headquarters_country":
                                       "Lebanon", "headquarters_city": "Beirut"})
    agent.post("/companies", json={"name": "Delta Foods", "industry": "Food Manufacturing",
                                   "headquarters_country": "Lebanon", "headquarters_city": "Tripoli"})  # elsewhere
    agent.post("/companies", json={"name": "Beirut Bank", "industry": "Financial Services",
                                   "headquarters_country": "Lebanon", "headquarters_city": "Beirut"})  # other industry
    (connector,) = sources(FakeConnector(config("gov"), lambda: [cand("Brand New Foods")]))
    done = search(agent, count=2)
    assert connector.calls == 1  # Find Leads always looks for companies LeadFinder does not have
    rows = results(agent, done["id"])
    assert [r["company"]["name"] for r in rows] == ["Brand New Foods"] and all(r["is_new"] for r in rows)
    assert done["status"] == "partial" and "3 matching companies are already in LeadFinder" in done["message"]


def test_discovery_returns_only_new_companies(client_for, db, sources, web):
    agent, _ = client_for(UserRole.SALES_AGENT)
    agent.post("/companies", json={"name": "Known Foods", "industry": "Food Manufacturing",
                                   "headquarters_country": "Lebanon", "headquarters_city": "Beirut"})
    sources(FakeConnector(config("gov"), lambda: [cand("Known Foods", n=9)] +
                          [cand(f"New Foods {i}", n=i) for i in range(1, 6)]))
    created = agent.post("/lead-searches", json={"country": "Lebanon", "city": "Beirut", "industry":
                                                 "Food Manufacturing", "requested_count": 3})
    assert (created.json()["status"], created.json()["companies_found"]) == ("researching", 0)  # returned at once
    jobs.run_next()
    done = agent.get(f"/lead-searches/{created.json()['id']}").json()
    assert (done["status"], done["companies_found"]) == ("completed", 3)
    assert count(db, Company) == 4  # the known one + exactly 3 new, not 5
    rows = results(agent, done["id"])
    assert all(r["is_new"] for r in rows) and "Known Foods" not in {r["company"]["name"] for r in rows}


# ---- 4-6: connectors, candidates, normalization -------------------------------------------------------------


def test_dataset_file_connector_returns_candidates(tmp_path):
    from app.services.discovery.connectors.dataset_file import DatasetFileConnector
    from app.services.discovery.geography import find_area, find_country
    from app.services.discovery.industries import profile_for

    (tmp_path / "list.csv").write_text(
        "Name,Reg,Town,Sector,Tel\nCedar Dairy SAL,1001,Beirut,Dairy products manufacturing,01 234 567\n"
        "Cedar Bank,1002,Beirut,Banking,01 999 999\nZahle Foods,1003,Zahle,Food industry,08 111 111\n",
        encoding="utf-8")
    cfg = ConnectorConfig(key="lb_gov", kind="dataset_file", enabled=True, countries=("LB",), priority=1,
                          source_type="government", quality=90, label="Ministry list",
                          options={"path": "list.csv", "columns": {"company_name": "Name", "registration_number":
                                   "Reg", "city": "Town", "industry": "Sector", "phone": "Tel"}})
    connector = DatasetFileConnector(cfg, base_dir=tmp_path)
    lb = find_country("LB")
    result = connector.search_companies(SearchQuery(lb, find_area("LB", "Beirut"), profile_for("Food Manufacturing"), 10))
    assert [c.company_name for c in result.candidates] == ["Cedar Dairy SAL"]
    c = result.candidates[0]
    assert isinstance(c, CompanyCandidate)
    assert (c.source_type, c.registration_number, c.external_id, c.region) == ("government", "1001", "1001", "Beirut")
    with pytest.raises(ConnectorError):
        DatasetFileConnector(cfg, base_dir=tmp_path / "missing").search_companies(
            SearchQuery(lb, None, profile_for(""), 10))


def test_candidate_normalization_keeps_the_original():
    from app.services.discovery.geography import find_country
    from app.services.discovery.industries import profile_for
    from app.services.discovery.normalizer import normalize

    lb = find_country("Lebanon")
    names = ["ABC S.A.L.", "ABC SAL", "ABC sal", "ABC Sarl", "  ABC   s.a.l "]
    normalized = [normalize(cand(n, city="Beyrouth", at=(None, None)), lb, profile_for("Food Manufacturing"))
                  for n in names]
    assert {n.normalized_name for n in normalized} == {"abc"}
    first = normalized[0]
    c = first.candidate
    assert c.company_name == "ABC S.A.L." and c.legal_name == "ABC S.A.L."  # display value untouched
    assert (c.city, c.region, c.country) == ("Beirut", "Beirut", "Lebanon")
    assert first.phone == "+9611200000" and first.industry == "Food Manufacturing"
    assert c.raw_metadata["original"]["city"] == "Beyrouth"
    odd = normalize(cand("X Foods", website="www.XFoods.com.lb/about", email=" Info@XFoods.com.lb ",
                         phone="01 234 567"), lb, profile_for(""))
    assert (odd.candidate.website, odd.domain, odd.email, odd.phone) == (
        "https://www.XFoods.com.lb/about", "xfoods.com.lb", "info@xfoods.com.lb", "+9611234567")


@pytest.mark.parametrize("url,website,domain,social", [
    ("https://www.abcfoods.com.lb/about", "https://www.abcfoods.com.lb/about", "abcfoods.com.lb", {}),
    ("abcfoods.com", "https://abcfoods.com", "abcfoods.com", {}),
    ("https://www.facebook.com/abcfoods", None, None, {"facebook_url": "https://www.facebook.com/abcfoods"}),
    ("https://instagram.com/abc", None, None, {"instagram_url": "https://instagram.com/abc"}),
    ("https://linktr.ee/abc", None, None, {}),
    ("javascript:alert(1)", None, None, {}),
    ("not a url", None, None, {}),
    (None, None, None, {}),
])
def test_domain_resolution(url, website, domain, social):
    from app.services.discovery.domain_resolution import resolve_website

    resolved = resolve_website(url)
    assert (resolved.website, resolved.domain, resolved.social) == (website, domain, social)


# ---- 7-12: entity resolution, sources, evidence ---------------------------------------------------------------


def test_strong_domain_match_reuses_the_canonical_company(client_for, db, sources, web):
    agent, _ = client_for(UserRole.SALES_AGENT)
    cid = agent.post("/companies", json={"name": "ABC Foods Holding", "domain": "abcfoods.example",
                                         "headquarters_country": "Lebanon"}).json()["id"]
    sources(FakeConnector(config("gov"), lambda: [cand("ABC Food Industries", website="https://www.abcfoods.example/x",
                                                       phone=None)]))
    done = search(agent, count=1)
    assert count(db, Company) == 1  # the same company (strong domain match): never a duplicate ...
    assert results(agent, done["id"]) == []  # ... and not offered as a new lead
    assert cid


def test_strong_phone_match_reuses_the_canonical_company(client_for, db, sources, web):
    agent, _ = client_for(UserRole.SALES_AGENT)
    cid = agent.post("/companies", json={"name": "Hadid Sweets", "headquarters_country": "Lebanon"}).json()["id"]
    db.add(Phone(company_id=cid, phone="01 456 789", normalized_phone="+9611456789"))
    db.commit()
    sources(FakeConnector(config("gov"), lambda: [cand("Hadid Sweets Factory", phone="+961-1-456789")]))
    search(agent, count=1)
    assert count(db, Company) == 1  # the same company (strong phone match): never a duplicate
    # A shared number under another name is not the same company: a possible duplicate, not a merge.
    sources(FakeConnector(config("osm"), lambda: [cand("Totally Different Mills", connector="osm",
                                                       phone="+961 1 456 789", n=3)]))
    search(agent, count=2)
    assert count(db, Company) == 2 and count(db, PossibleDuplicate) == 1


def test_weak_name_only_match_is_never_merged(client_for, db, sources, web):
    agent, _ = client_for(UserRole.SALES_AGENT)
    for city in ("Tripoli", "Saida"):
        agent.post("/companies", json={"name": "ABC Trading", "headquarters_country": "Lebanon",
                                       "headquarters_city": city})
    sources(FakeConnector(config("gov"), lambda: [cand("ABC Trading")]))
    search(agent, count=1)
    assert count(db, Company) == 3  # a new Beirut "ABC Trading", the other two untouched
    pairs = db.scalars(select(PossibleDuplicate)).all()
    assert len(pairs) == 2 and all(p.status == "open" and "different" in p.reason for p in pairs)
    # Same name AND same city: that is enough (medium evidence) to reuse the company.
    sources(FakeConnector(config("osm"), lambda: [cand("ABC Trading", connector="osm", phone=None, n=5)]))
    search(agent, count=1)
    assert count(db, Company) == 3


def test_one_company_many_sources_with_evidence(client_for, db, sources, web):
    agent, _ = client_for(UserRole.SALES_AGENT)
    sources(FakeConnector(config("gov", quality=90, source_type="government", priority=5),
                          lambda: [cand("Kova Coffee", website="http://KovaCoffee.example/", registration_number="77")]),
            FakeConnector(config("osm", quality=55), lambda: [cand("Kova coffee", connector="osm",
                                                                   website="https://kovacoffee.example")]))
    done = search(agent, count=1)
    assert done["status"] == "completed" and count(db, Company) == 1
    company = db.scalar(select(Company))
    detail = agent.get(f"/companies/{company.id}").json()
    assert {s["source_type"] for s in detail["sources"]} == {"government", "open_dataset"}
    industry = db.scalars(select(Evidence).where(Evidence.field_name == "industry")).all()
    assert {e.extracted_value for e in industry} == {"Food Manufacturing"}
    assert {db.get(Source, e.source_id).source_quality for e in industry} == {90, 55}
    assert all(e.structured_value["tier"] == "category" for e in industry)
    assert db.scalar(select(func.count()).where(CompanyIdentifier.scheme == "registry:LB")) == 1
    rows = results(agent, done["id"])
    assert len(rows) == 1 and rows[0]["source_count"] == 2 and rows[0]["company"]["identity_confidence"]


def test_branches_consolidate_into_one_company_with_locations(client_for, db, sources, web):
    agent, _ = client_for(UserRole.SALES_AGENT)
    sources(FakeConnector(config("gov"), lambda: [
        cand("Patchi Hamra", n=0, phone="+961 1 111 001", brand="Patchi"),
        cand("Patchi Achrafieh", n=4, phone="+961 1 111 002", brand="Patchi"),
        cand("Patchi Verdun", n=8, phone=None, website="https://patchi.example", brand="Patchi"),
    ]))
    search(agent, count=5)
    companies = db.scalars(select(Company)).all()
    assert [c.name for c in companies] == ["Patchi"]
    assert count(db, CompanyLocation) == 3


# ---- 13-17: idempotency, growth, failures, statuses ------------------------------------------------------------


def test_repeating_a_search_finds_the_next_new_companies(client_for, db, sources, web):
    agent, _ = client_for(UserRole.SALES_AGENT)
    sources(FakeConnector(config("gov"), lambda: [cand(f"Food Co {i}", n=i) for i in range(1, 5)]))
    first = search(agent, count=4)
    before = {m: count(db, m) for m in (Company, Source, Evidence, CompanyLocation, Phone, CompanyIdentifier)}
    second = search(agent, count=4)  # the source has nothing more: nothing duplicated, nothing re-offered
    assert (first["status"], second["status"]) == ("completed", "partial")
    assert {m: count(db, m) for m in before} == before
    assert results(agent, second["id"]) == []
    assert "4 matching companies are already in LeadFinder" in second["message"]


def test_each_search_grows_the_database_with_new_companies(client_for, db, sources, web):
    agent, _ = client_for(UserRole.SALES_AGENT)
    sources(FakeConnector(config("gov"), lambda: [cand(f"Food Co {i}", n=i) for i in range(1, 9)]))
    first = search(agent, count=3)
    second = search(agent, count=3)  # Find Leads again: the next three, never the first three again
    assert count(db, Company) == 6
    old = {r["company"]["id"] for r in results(agent, first["id"])}
    rows = results(agent, second["id"])
    assert len(rows) == 3 and not old & {r["company"]["id"] for r in rows} and all(r["is_new"] for r in rows)


def test_a_failing_connector_does_not_stop_the_search(client_for, db, sources, web):
    agent, _ = client_for(UserRole.SALES_AGENT)
    manager, _ = client_for(UserRole.SALES_MANAGER)
    sources(FakeConnector(config("gov", priority=1), error=ConnectorError("Registry is down for maintenance.")),
            FakeConnector(config("dir", priority=2), error=RuntimeError("psycopg password=hunter2 /app/x.py")),
            FakeConnector(config("osm", priority=3), lambda: [cand("Survivor Foods", connector="osm")]))
    done = search(agent, count=1)
    assert (done["status"], done["companies_found"]) == ("completed", 1)
    assert (done["connectors_total"], done["connectors_completed"]) == (3, 3)
    assert done["diagnostics"] is None  # salespeople do not see diagnostics
    diagnostics = manager.get(f"/lead-searches/{done['id']}").json()["diagnostics"]["connectors"]
    assert diagnostics["gov"]["error"] == "Registry is down for maintenance."
    assert "hunter2" not in str(diagnostics) and diagnostics["dir"]["status"] == "failed"
    assert diagnostics["osm"]["created"] == 1


def test_a_slow_source_never_holds_the_search(client_for, db, sources, web, monkeypatch):
    agent, _ = client_for(UserRole.SALES_AGENT)
    manager, _ = client_for(UserRole.SALES_MANAGER)
    monkeypatch.setattr(orchestrator, "PRIORITY_GRACE_SECONDS", 0.1)
    monkeypatch.setattr(get_settings(), "discovery_connector_timeout_seconds", 0.5)
    release = threading.Event()

    def hangs():
        release.wait(5)
        return [cand("Too Late Foods")]

    sources(FakeConnector(config("gov", priority=1), hangs),  # the best source, but it does not answer
            FakeConnector(config("osm", priority=2), lambda: [cand("Fast Foods", connector="osm")]))
    started = time.monotonic()
    done = search(agent, count=1)
    release.set()
    assert time.monotonic() - started < 3
    assert (done["status"], done["companies_found"]) == ("completed", 1)
    gov = manager.get(f"/lead-searches/{done['id']}").json()["diagnostics"]["connectors"]["gov"]
    assert gov["status"] == "failed" and "No answer within" in gov["error"]


def test_discovery_stops_matching_once_the_search_is_full(client_for, db, sources, web):
    manager, _ = client_for(UserRole.SALES_MANAGER)
    def word(i: int) -> str:  # distinct names: aaa, aab, ...
        return "".join("abcdefghij"[int(d)] for d in f"{i:03d}")

    sources(FakeConnector(config("gov"), lambda: [cand(f"Foods {word(i)}", n=i) for i in range(300)]))
    done = search(manager, count=3)
    assert (done["status"], count(db, Company)) == ("completed", 3)
    stats = done["diagnostics"]["connectors"]["gov"]
    assert stats["not_matched"] > 250  # listings the search did not need were never matched against the database
    assert {"db_lookup", "queue_wait", "normalize", "deduplicate", "persist", "rank", "first_result",
            "discovery_total"} <= set(done["diagnostics"]["timings"])


def test_partial_failed_and_completed_statuses(client_for, db, sources, web):
    agent, _ = client_for(UserRole.SALES_AGENT)
    sources(FakeConnector(config("gov"), lambda: [cand(f"Only Co {i}", n=i) for i in range(3)]
                          + [cand("Pin Only", phone=None, address=None, n=9, tier="name", categories=[])]))
    partial = search(agent, count=10)
    assert (partial["status"], partial["companies_found"]) == ("partial", 3)  # never padded with junk
    assert "Only 3 new companies" in partial["message"]
    assert count(db, Company) == 3
    sources(FakeConnector(config("gov"), error=ConnectorError("down")))
    failed = search(agent, count=2, city="Tripoli")
    assert failed["status"] == "failed" and failed["companies_found"] == 0
    unsupported = agent.post("/lead-searches", json={"country": "France", "requested_count": 5}).json()
    assert unsupported["status"] == "partial" and "not available for France" in unsupported["message"]


# ---- 18-21: Companies, deletion, visibility, auth -------------------------------------------------------------


def test_discovered_companies_appear_in_companies_and_stay_deleted(client_for, db, sources, web):
    agent, _ = client_for(UserRole.SALES_AGENT)
    manager, _ = client_for(UserRole.SALES_MANAGER)
    sources(FakeConnector(config("gov"), lambda: [cand("Listed Foods", n=1), cand("Junk Foods", n=2)]))
    search(agent, count=2)
    listed = agent.get("/companies", params={"region": "Beirut", "industry": "Food Manufacturing"}).json()
    assert {c["name"] for c in listed["items"]} == {"Listed Foods", "Junk Foods"}
    junk = next(c["id"] for c in listed["items"] if c["name"] == "Junk Foods")
    assert manager.delete(f"/companies/{junk}").status_code == 204
    again = search(agent, count=2)
    assert again["companies_found"] == 0 and count(db, Company) == 1  # deleted means deleted (Listed: known)
    stats = manager.get(f"/lead-searches/{again['id']}").json()["diagnostics"]["connectors"]["gov"]
    assert (stats["suppressed"], stats["already_known"]) == (1, 1)


def test_searches_are_private_to_their_owner(client_for, sources):
    hussein, _ = client_for(UserRole.SALES_AGENT)
    mariam, _ = client_for(UserRole.SALES_AGENT)
    manager, _ = client_for(UserRole.SALES_MANAGER)
    sources()
    sid = hussein.post("/lead-searches", json={"country": "Lebanon"}).json()["id"]
    assert mariam.get(f"/lead-searches/{sid}").status_code == 404
    assert mariam.get(f"/lead-searches/{sid}/results").status_code == 404
    assert manager.get(f"/lead-searches/{sid}").status_code == 200
    assert hussein.get(f"/lead-searches/{sid}/results").status_code == 200


# ---- website identity check -----------------------------------------------------------------------------------


def test_company_research_sets_only_verified_domains(client_for, db, sources, web):
    agent, _ = client_for(UserRole.SALES_AGENT)
    web["www.goodfoods.example"] = "<html><title>Good Foods SAL | Home</title><p>Dairy since 1990</p></html>"
    web["wrongsite.example"] = "<html><title>Totally unrelated shop</title></html>"
    web["parked.example"] = "<html><title>parked.example - This domain is for sale</title></html>"
    sources(FakeConnector(config("gov"), lambda: [
        cand("Good Foods", website="https://www.goodfoods.example", n=1),
        cand("Mismatch Mills", website="https://wrongsite.example", n=2),
        cand("Parked Dairy", website="https://parked.example", n=3),
        cand("Dead Foods", website="https://dead.example", n=4),
    ]))
    created = agent.post("/lead-searches", json={"country": "Lebanon", "city": "Beirut", "industry":
                                                 "Food Manufacturing", "requested_count": 4}).json()
    assert jobs.run_next((jobs.DISCOVERY,))
    found = agent.get(f"/lead-searches/{created['id']}").json()
    # The search is final before any website is fetched; company research follows as its own jobs.
    assert (found["status"], found["companies_found"], found["enrichment_status"]) == ("completed", 4, "running")
    assert len(results(agent, created["id"])) == 4 and count(db, Source) == 4  # no website source yet
    while jobs.run_next():  # company research of the 4 companies, then their people discovery
        pass
    assert agent.get(f"/lead-searches/{created['id']}").json()["enrichment_status"] == "completed"
    domains = {c.name: (c.domain, c.last_verified_at is not None) for c in db.scalars(select(Company))}
    assert domains == {"Good Foods": ("goodfoods.example", True), "Mismatch Mills": (None, False),
                       "Parked Dairy": (None, False), "Dead Foods": (None, False)}
    good = db.scalar(select(Company).where(Company.name == "Good Foods"))
    proof = db.scalar(select(Evidence).where(Evidence.company_id == good.id, Evidence.field_name == "domain"))
    assert db.get(Source, proof.source_id).source_type == "company_website"
    assert good.website == "https://www.goodfoods.example"


def test_polite_fetcher_honours_robots_and_caches():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private", headers={"content-type": "text/plain"})
        return httpx.Response(200, text="<p>ok</p>", headers={"content-type": "text/html"})

    import app.services.discovery.fetch as f
    original, f.resolve = f.resolve, lambda host: ["93.184.216.34"]
    try:
        polite = PoliteFetcher(f.Fetcher(max_bytes=10_000, timeout=5, transport=httpx.MockTransport(handler)),
                               min_interval=0)
        assert polite.get("https://site.example/").html == "<p>ok</p>"
        polite.get("https://site.example/")  # cached
        with pytest.raises(f.FetchError) as exc:
            polite.get("https://site.example/private/x")
        assert exc.value.kind == "ROBOTS"
    finally:
        f.resolve = original
    assert calls == ["/robots.txt", "/"]


# ---- the job queue ----------------------------------------------------------------------------------------------


def test_jobs_run_once_and_interrupted_jobs_are_recovered(client_for, db, sources):
    agent, user = client_for(UserRole.SALES_AGENT)
    sources()
    for _ in range(2):
        agent.post("/lead-searches", json={"country": "Lebanon"})
    assert jobs.run_next() and jobs.run_next() and not jobs.run_next()
    assert set(db.scalars(select(ResearchRun.status))) == {"partial"}
    stuck = LeadSearch(user_id=user.id, country="Lebanon", requested_count=5, status="researching")
    db.add(stuck)
    db.flush()
    dead = ResearchRun(search_id=stuck.id, research_type="company_discovery", status="running")
    alive = ResearchRun(research_type="company_discovery", status="running")
    db.add_all([dead, alive])
    db.commit()
    with engine.connect() as worker:  # a live worker holds its job's liveness lock
        worker.execute(select(func.pg_advisory_lock(jobs._LIVENESS, alive.id)))
        assert jobs.recover_interrupted(db) == 1  # only the job nobody runs any more
        worker.execute(select(func.pg_advisory_unlock(jobs._LIVENESS, alive.id)))
        worker.commit()
    db.refresh(stuck)
    db.refresh(alive)
    assert stuck.status == "failed" and "interrupted" in stuck.message and alive.status == "running"  # found none


def test_results_are_ranked_by_relevance(client_for, db, sources, web):
    agent, _ = client_for(UserRole.SALES_AGENT)
    sources(FakeConnector(config("gov"), lambda: [
        cand("Name Only Bakery Factory", n=1, tier="name", categories=[], website="https://nameonly.example"),
        cand("Category Foods", n=2, website="https://catfoods.example"),
    ]))
    done = search(agent, count=2)
    rows = results(agent, done["id"])
    assert [r["company"]["name"] for r in rows] == ["Category Foods", "Name Only Bakery Factory"]
    assert rows[0]["relevance_score"] > rows[1]["relevance_score"] and [r["rank"] for r in rows] == [1, 2]
    assert db.scalar(select(func.count(LeadSearchResult.id))) == 2
