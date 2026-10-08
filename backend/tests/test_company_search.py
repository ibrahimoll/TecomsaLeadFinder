"""Direct company search (Step 5.4): database first (exact / legal / alias / Arabic / French / domain / URL / brand /
transliteration / typo), ranking and confidence, ambiguity never auto-resolved, then a bounded public-source lookup
(local corpus, discovery extracts, Wikidata, the website) creating a company only on strong evidence, through
discovery's duplicate resolution; caches, permissions, research queued. Every page and API is mocked."""

import time

import pytest
from sqlalchemy import func, select

from app.models import Company, CompanyAlias, CompanyLookup, ResearchRun
from app.models.enums import UserRole
from app.services import company_lookup, company_search, jobs, web_discovery
from app.services.discovery import orchestrator
from app.services.people.external.lebanon.records import Record

from .test_discovery import FakeConnector, cand, config
from .test_external_people import web  # noqa: F401  (fixture)
from .test_lebanon_sources import keep, new_company


@pytest.fixture(autouse=True)
def no_extracts(monkeypatch):
    """Discovery extracts (Overture / OSM / dataset files) are fakes: none unless a test installs one."""
    installed: list = []
    monkeypatch.setattr(orchestrator, "build_connectors", lambda country: list(installed))
    monkeypatch.setattr(company_lookup, "_INDEX", {})  # the in-process extract index: per test
    monkeypatch.setattr(web_discovery, "providers", lambda: [])  # web discovery: none unless a test installs one
    web_discovery.Breaker.reset()
    return installed


def names(hits) -> list[str]:
    return [h.company.name for h in hits]


def lookup(client, q, **kw) -> dict:
    response = client.post("/companies/lookup", json={"q": q, "country": "Lebanon", **kw})
    assert response.status_code == 200, response.text
    return response.json()


def count(db, model, *where) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(model).where(*where))


# ---- database search ---------------------------------------------------------------------------------------------


def test_exact_legal_domain_url_alias_and_transliteration(client_for, db):
    agent, _ = client_for(UserRole.SALES_AGENT)
    kassatly = new_company(agent, "Kassatly Chtaura", industry="Food Manufacturing", website="https://www.kassatly.net")
    new_company(agent, "Kassatly Trading", industry="Distribution")
    db.add(CompanyAlias(company_id=kassatly, alias="كساتلي شتورا", normalized_alias="شتورا كساتلي",
                        alias_type="arabic", skeleton_key=company_search.skeleton_key("كساتلي شتورا")))
    db.add(CompanyAlias(company_id=kassatly, alias="Société Kassatly Chtaura", normalized_alias="chtaura kassatly",
                        alias_type="french"))
    db.commit()
    for query, match in [("Kassatly Chtaura", "exact_name"), ("KASSATLY CHTAURA S.A.L.", "normalized_name"),
                         ("Chtaura Kassatly sal", "normalized_name"), ("kassatly.net", "domain"),
                         ("https://www.kassatly.net/en/about", "domain"), ("كساتلي شتورا", "exact_alias"),
                         ("Kassatli Chtaura", "transliteration")]:
        hits = company_search.search(db, query, country="Lebanon")
        outcome, chosen = company_search.resolve(hits)
        assert (outcome, chosen[0].company.id, chosen[0].match_type) == ("found", kassatly, match), query
    hits = company_search.search(db, "Kassatly", country="Lebanon")  # two companies carry the brand
    assert company_search.resolve(hits)[0] == "ambiguous"
    hits = company_search.search(db, "Kasatly Chtora", country="Lebanon")  # a typo: offered, never opened alone
    assert names(hits)[0] == "Kassatly Chtaura" and company_search.resolve(hits)[0] in ("found", "possible")


def test_exact_and_domain_outrank_fuzzy_and_location_breaks_ties(client_for, db):
    agent, _ = client_for(UserRole.SALES_AGENT)
    beirut = new_company(agent, "ABC Trading", industry="Distribution")
    tripoli = new_company(agent, "ABC Trading SARL", industry="Construction")
    db.get(Company, beirut).headquarters_city = "Beirut"
    db.get(Company, tripoli).headquarters_city = "Tripoli"
    new_company(agent, "ABD Trading", industry="Distribution", website="https://abc-trading.example")
    db.commit()
    hits = company_search.search(db, "ABC Trading")
    assert company_search.resolve(hits)[0] == "ambiguous"  # never a guess between two entities
    outcome, chosen = company_search.resolve(company_search.search(db, "ABC Trading", city="Tripoli"),
                                             city="Tripoli")
    assert (outcome, chosen[0].company.id) == ("found", tripoli)
    hits = company_search.search(db, "abc-trading.example")
    assert hits[0].match_type == "domain" and hits[0].company.name == "ABD Trading"  # the domain wins


def test_group_and_subsidiary_and_brand_core(client_for, db):
    agent, _ = client_for(UserRole.SALES_AGENT)
    group = new_company(agent, "Omega Group", industry="Holding")
    foods = new_company(agent, "Omega Foods", industry="Food Manufacturing")
    blom = new_company(agent, "BLOM Bank", industry="Banking")
    assert company_search.resolve(company_search.search(db, "Omega Group"))[1][0].company.id == group
    assert company_search.resolve(company_search.search(db, "Omega Foods SAL"))[1][0].company.id == foods
    outcome, chosen = company_search.resolve(company_search.search(db, "BLOM"))
    assert (outcome, chosen[0].company.id, chosen[0].match_type) == ("found", blom, "brand_core")


def test_existing_company_opens_at_once_and_queues_only_due_research(client_for, db):
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = new_company(agent, "Omega Foods", industry="Food Manufacturing")
    db.query(ResearchRun).delete()
    db.commit()
    started = time.perf_counter()
    result = lookup(agent, "Omega Foods")
    assert result["status"] == "found" and result["company"]["company_id"] == company_id
    assert result["external_used"] is False and time.perf_counter() - started < 2
    runs = db.scalars(select(ResearchRun).where(ResearchRun.company_id == company_id)).all()
    assert {r.priority for r in runs} == {company_search.DIRECT_LOOKUP}  # never researched: due, first in line
    lookup(agent, "Omega Foods")
    assert count(db, ResearchRun, ResearchRun.company_id == company_id) == len(runs)  # one active job per kind


# ---- public-source lookup ----------------------------------------------------------------------------------------


def test_unknown_company_created_from_a_curated_source_with_research_queued(client_for, db):
    agent, _ = client_for(UserRole.SALES_AGENT)
    keep(db, "ministry_industry", "https://industry.example/list.xls", [
        Record(org=["Delta Snacks SAL"], identifiers={"moi_factory": "77"},
               facts={"phone": "+961 1 456789", "city": "Zahle"}, excerpt="Delta Snacks SAL, Zahle")])
    result = lookup(agent, "Delta Snacks")
    assert result["status"] == "created" and result["created"] and result["external_used"]
    company_id = result["company"]["company_id"]
    company = db.get(Company, company_id)
    assert company.name == "Delta Snacks SAL" and company.headquarters_country == "Lebanon"
    assert {r.research_type for r in db.scalars(select(ResearchRun).where(ResearchRun.company_id == company_id))} \
        & {jobs.PEOPLE, jobs.ENRICHMENT}  # research queued at once (people research follows)
    assert [c["id"] for c in agent.get("/companies", params={"q": "Delta"}).json()["items"]] == [company_id]
    for again in ("Delta Snacks", "DELTA SNACKS S.A.L.", "Delta Snacks sarl"):  # the same entity, never twice
        assert lookup(agent, again)["company"]["company_id"] == company_id
    assert count(db, Company, Company.name.ilike("%delta%")) == 1


def test_domain_lookup_reuses_the_known_company_and_learns_its_website(client_for, db, web, no_extracts):
    agent, _ = client_for(UserRole.SALES_AGENT)
    keep(db, "ministry_industry", "https://industry.example/list.xls", [
        Record(org=["Delta Snacks SAL"], identifiers={"moi_factory": "77"}, excerpt="Delta Snacks SAL")])
    created = lookup(agent, "Delta Snacks")["company"]["company_id"]
    web.sites["deltasnacks.example"] = {"/": "<html><head><title>Delta Snacks | Home</title></head><body>Snacks"
                                              "</body></html>"}
    result = lookup(agent, "deltasnacks.example")
    assert (result["status"], result["company"]["company_id"]) == ("found", created)  # reused, not duplicated
    assert count(db, Company) == 1
    assert db.get(Company, created).website  # the next domain search is a database hit
    assert lookup(agent, "https://www.deltasnacks.example/")["external_used"] is False


def test_ambiguous_public_candidates_are_offered_and_picked_never_guessed(client_for, db, no_extracts):
    agent, _ = client_for(UserRole.SALES_AGENT)
    no_extracts.append(FakeConnector(config("osm"), lambda: [
        cand("Sigma Foods", connector="osm", n=1, website="https://sigma-one.example", city="Beirut"),
        cand("Sigma Foods", connector="osm", n=40, website="https://sigma-two.example", city="Tripoli",
             at=(34.43, 35.84))]))
    result = lookup(agent, "Sigma Foods")
    assert result["status"] == "ambiguous" and count(db, Company) == 0  # two entities: nothing created
    picks = [c for c in result["candidates"] if c["pick_index"] is not None]
    assert len(picks) == 2 and all("payload" not in c for c in result["candidates"])
    chosen = next(c for c in picks if c["city"] == "Tripoli")
    other, _ = client_for(UserRole.SALES_AGENT, email="other@example.com")
    assert other.post(f"/companies/lookup/{result['lookup_id']}/select", json={"index": 0}).status_code == 404
    picked = agent.post(f"/companies/lookup/{result['lookup_id']}/select", json={"index": chosen["pick_index"]})
    assert picked.status_code == 200 and picked.json()["status"] == "created"
    assert db.get(Company, picked.json()["company"]["company_id"]).headquarters_city == "Tripoli"


def test_weak_or_foreign_evidence_never_creates_a_company(client_for, db, public_apis, no_extracts):
    agent, _ = client_for(UserRole.SALES_AGENT)
    no_extracts.append(FakeConnector(config("overture"), lambda: [
        cand("Sigmah Foodz Factory", connector="overture", n=1)]))  # a similar spelling only
    public_apis.routes[("www.wikidata.org", "/w/api.php")] = lambda r: __import__("httpx").Response(200, json={
        "search": [{"id": "Q483915"}], "entities": {"Q483915": {
            "labels": {"en": {"value": "Nike"}}, "claims": {"P17": [{"mainsnak": {"datavalue": {
                "value": {"id": "Q30"}}}}]}}}})  # Nike, Inc. (United States)
    assert lookup(agent, "Sigma Foods")["status"] in ("ambiguous", "not_found")
    assert lookup(agent, "Nike")["status"] == "not_found"  # the global brand is not the local entity
    assert count(db, Company) == 0


def test_lookup_deadline_negative_cache_and_no_public_call_while_typing(client_for, db, public_apis, monkeypatch):
    agent, _ = client_for(UserRole.SALES_AGENT)
    calls = []

    def slow(q, country, intent=None):
        calls.append(q.raw)
        return [[("extracts", lambda: time.sleep(6) or [])]]

    monkeypatch.setattr(company_lookup, "_sources", slow)
    monkeypatch.setattr(company_search, "LOOKUP_SECONDS", 4)
    started = time.perf_counter()
    result = lookup(agent, "Unknown Zeta Holding")
    assert result["status"] == "timed_out" and time.perf_counter() - started < 5.5  # bounded, ends
    monkeypatch.setattr(company_lookup, "_sources", lambda q, country, intent=None: calls.append(q.raw) or [])
    assert lookup(agent, "Unknown Zeta Holding")["status"] == "not_found"
    assert lookup(agent, "unknown zeta holding s.a.l.")["status"] == "not_found"
    assert len(calls) == 2  # the third was answered by the negative cache (same normalized query)
    before = len(public_apis.requests)
    response = agent.get("/companies/search", params={"q": "Zeta"})
    assert response.status_code == 200 and response.json() == [] and len(public_apis.requests) == before
    assert len(calls) == 2  # autocomplete is the database only
    stored = db.scalars(select(CompanyLookup).order_by(CompanyLookup.id)).all()
    assert [s.status for s in stored] == ["timed_out", "not_found", "not_found"]
    assert stored[0].duration_ms and stored[0].external_used and stored[0].sources


def test_search_requires_login_and_uses_no_paid_or_linkedin_source(anon_client, client_for):
    assert anon_client.get("/companies/search", params={"q": "Omega"}).status_code == 401
    assert anon_client.post("/companies/lookup", json={"q": "Omega"}).status_code == 401
    from app.services.discovery.geography import find_country

    lebanon = find_country("Lebanon")
    tiers = company_lookup._sources(company_search.parse("x.example"), lebanon)
    assert [[name for name, _ in tier] for tier in tiers] == [["extracts", "website"], ["wikidata"]]
    tiers = company_lookup._sources(company_search.parse("Omega Foods"), lebanon)
    assert [[name for name, _ in tier] for tier in tiers] == [["extracts"], ["web_discovery"], ["wikidata"]]  # never
    # a paid
    # search API or LinkedIn; Wikidata (rate-limited) only when the cheaper sources found nothing strong
