"""External people discovery (Step 5.1): query planning, provider-neutral search (snippets are never facts),
source filtering, secure fetch + cache of pages and PDFs, strict company matching, recency, independence,
budgets / early stop / failure isolation. Search provider and websites are mocked."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.models import (Company, CompanyPerson, Email, Evidence, ExternalDocument, ExternalSearchCache, Person, Phone,
                        Source)
from app.models.enums import UserRole
from app.services import jobs
from app.services.discovery import fetch
from app.services.discovery.fetch import Fetcher
from app.services.discovery.web import PoliteFetcher
from app.services.enrichment import orchestrator as enrichment
from app.services.people.external import documents, orchestrator as external, planner, search
from app.services.people.external.search import BraveSearchProvider, SearchResult
from app.services.people.external.sources import blocked, kind_of

NOW_YEAR = datetime.now(timezone.utc).year


def make_pdf(pages: list[list[str]], title: str = "Programme") -> bytes:
    """A small, valid PDF with one text line per entry (native text, as real programmes / reports have)."""
    objects = ["<</Type/Catalog/Pages 2 0 R>>", None, "<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>"]
    kids = []
    for lines in pages:
        text = "BT /F1 11 Tf 72 740 Td " + " ".join(
            f"({line.replace('(', '[').replace(')', ']')}) Tj 0 -16 Td" for line in lines) + " ET"
        objects.append(f"<</Length {len(text)}>>\nstream\n{text}\nendstream")
        objects.append(f"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents {len(objects)} 0 R"
                       f"/Resources<</Font<</F1 3 0 R>>>>>>")
        kids.append(f"{len(objects)} 0 R")
    objects[1] = f"<</Type/Pages/Kids[{' '.join(kids)}]/Count {len(kids)}>>"
    objects.append(f"<</Title({title})/CreationDate(D:{NOW_YEAR}0301000000)>>")
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += (f"trailer\n<</Size {len(objects) + 1}/Root 1 0 R/Info {len(objects)} 0 R>>\nstartxref\n{xref}\n%%EOF"
            ).encode()
    return out


HOME = """<html><head><title>ABC Foods | Biscuits</title></head><body><nav><a href="/about-us">About us</a>
<a href="/files/annual-report-2025.pdf">Annual report 2025</a></nav><p>ABC Foods makes biscuits in Zahle.</p>
</body></html>"""
CONFERENCE = f"""<html><head><title>Lebanon Food Industry Summit {NOW_YEAR} - Speakers</title>
<meta property="article:published_time" content="{NOW_YEAR}-03-01"></head><body><h1>Speakers</h1>
<h3>Joseph Haddad</h3><p>IT Director, ABC Foods</p><p>Email: joseph.haddad@abcfoods.example</p>
<h3>Rami Khoury</h3><p>CEO, Delta Snacks</p>
<h3>Lina Saab</h3><p>Marketing Director at ABC Group</p></body></html>"""
OLD_CONFERENCE = """<html><head><title>Food Forum 2019 - Speakers</title>
<meta property="article:published_time" content="2019-05-01"></head><body>
<h3>Nadim Aoun</h3><p>Sales Director, ABC Foods</p></body></html>"""
ASSOCIATION = """<html><head><title>Association of Lebanese Industrialists - Board</title></head><body>
<h2>Board of Directors</h2><p>Rita Saba - CFO, ABC Foods</p><p>Karim Nassar - Chairman, Nassar Paper Mills</p>
</body></html>"""
CASE_STUDY = f"""<html><head><title>Customer story: ABC Foods moves to the cloud</title>
<meta property="article:published_time" content="{NOW_YEAR}-02-10"></head><body>
<p>ABC Foods CIO Joseph Haddad explains how the move cut costs.</p>
<p>Joseph from ABC joined the project team.</p></body></html>"""
NEWS = f"""<html><head><title>ABC Foods opens a new line</title>
<meta property="article:published_time" content="{NOW_YEAR}-01-15"></head><body>
<p>ABC Foods CEO Michel Haddad said the new biscuit line will double exports.</p>
<p>Elie Matar discussed ABC Foods at length.</p></body></html>"""
DIRECTORY = """<html><head><title>ABC Foods - company profile - Lebanon directory</title></head><body>
<p>Contact: Fadi Salem, Procurement Manager, ABC Foods</p></body></html>"""
PROGRAMME = make_pdf([["Lebanon Industry Week", "Programme"],
                      ["Panel: Digital factories", "Joseph Haddad - IT Director, ABC Foods",
                       "Hana Fares - Procurement Manager, ABC Foods", "Sami Rizk - CFO, Omega Bank"]])
REPORT = make_pdf([["ABC Foods annual report 2025"], ["Management", "Michel Haddad - Chief Executive Officer",
                                                       "Rita Saba - Chief Financial Officer"]], "ABC Foods report")


@pytest.fixture
def web(monkeypatch):
    """Websites {host: {path: html | (bytes, content type) | Exception}} and a fake search provider."""
    sites: dict[str, dict] = {}
    requests: list[str] = []
    results: dict[str, list[SearchResult]] = {}  # query word -> results
    queries: list[str] = []
    monkeypatch.setattr(fetch, "resolve", lambda host: ["93.184.216.34"])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path != "/robots.txt":
            requests.append(f"{request.url.host}{request.url.path}")
        body = sites.get(request.url.host, {}).get(request.url.path)
        if isinstance(body, Exception):
            raise body
        if isinstance(body, tuple):
            return httpx.Response(200, content=body[0], headers={"content-type": body[1]})
        if body is None:
            return httpx.Response(404, text="nope", headers={"content-type": "text/html"})
        return httpx.Response(200, text=body, headers={"content-type": "text/html; charset=utf-8"})

    def polite(pdf=False, **_):
        inner = Fetcher(max_bytes=500_000, timeout=5, transport=httpx.MockTransport(handler), accept_pdf=pdf,
                        truncate=not pdf)
        return PoliteFetcher(inner, min_interval=0, retries=0)

    monkeypatch.setattr(enrichment, "website_fetcher", lambda: polite())
    monkeypatch.setattr(documents, "fetcher", lambda pdf: polite(pdf))
    from app.services.people.external.lebanon import pack

    monkeypatch.setattr(pack, "bulk_fetcher", lambda: polite(True))

    class FakeProvider:
        key, supports_quotes = "fake", True

        def search(self, query, *, limit, country=None, language=None):
            queries.append(query)
            if "fail" in results:
                raise search.SearchError("search provider answered HTTP 429")
            return [r for word, rs in results.items() if word.lower() in query.lower() for r in rs][:limit]

    state = SimpleNamespace(sites=sites, requests=requests, results=results, queries=queries, provider=FakeProvider())
    monkeypatch.setattr(search, "provider", lambda purpose="people": state.provider)
    return state


def hit(url: str, title: str, snippet: str = "", published: str | None = None) -> SearchResult:
    return SearchResult(title, url, snippet, httpx.URL(url).host, published)


def abc(client, web, *, website=True) -> int:
    web.sites["www.abcfoods.example"] = {"/": HOME, "/files/annual-report-2025.pdf": (REPORT, "application/pdf")}
    payload = {"name": "ABC Foods", "industry": "Food Manufacturing", "headquarters_country": "Lebanon",
               "headquarters_city": "Zahle", "website": "https://www.abcfoods.example" if website else None}
    return client.post("/companies", json=payload).json()["id"]


def research(client, company_id: int) -> list[dict]:
    client.get(f"/companies/{company_id}")
    while jobs.run_next((*jobs.RESEARCH, jobs.EXTERNAL)):
        pass
    return client.get(f"/companies/{company_id}/people").json()


def roles(db, company_id) -> dict[str, CompanyPerson]:
    db.expire_all()
    return {f"{n} | {r.job_title}": r for n, r in db.execute(
        select(Person.full_name, CompanyPerson).join(CompanyPerson).where(CompanyPerson.company_id == company_id))}


def count(db, model, *where) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(model).where(*where))


def full_web(web) -> None:
    web.sites.update({
        "summit.example": {"/speakers": CONFERENCE, "/2019/speakers": OLD_CONFERENCE,
                           "/programme.pdf": (PROGRAMME, "application/pdf")},
        "ali.example": {"/board": ASSOCIATION},
        "cloudvendor.example": {"/customer-stories/abc-foods": CASE_STUDY},
        "news.example": {f"/{NOW_YEAR}/01/abc-foods-new-line": NEWS},
        "copy.example": {"/business/abc-foods-new-line": NEWS},  # the same article, syndicated
        "lebanon-directory.example": {"/companies/abc-foods": DIRECTORY},
    })
    web.results["management"] = [
        hit("https://ali.example/board", "ALI board of directors", "ABC Foods"),
        hit("https://www.linkedin.com/in/joseph-haddad", "Joseph Haddad - IT Director - ABC Foods"),
        hit("https://summit.example/programme.pdf", "Lebanon Industry Week programme ABC Foods"),
        hit(f"https://news.example/{NOW_YEAR}/01/abc-foods-new-line", "ABC Foods opens a new line"),
        hit("https://copy.example/business/abc-foods-new-line", "ABC Foods opens a new line"),
        hit("https://summit.example/speakers", "Food Industry Summit speakers ABC Foods"),
        hit("https://cloudvendor.example/customer-stories/abc-foods", "Customer story: ABC Foods"),
        hit("https://summit.example/2019/speakers", "Food Forum 2019 speakers ABC Foods"),
        hit("https://lebanon-directory.example/companies/abc-foods", "ABC Foods company profile"),
        hit("https://elsewhere.example/delta", "Delta Snacks news", "nothing about the company")]


# ---- planning ----------------------------------------------------------------------------------------------------


def test_aliases_and_query_plan_cover_only_missing_departments(client_for, db, web):
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = agent.post("/companies", json={"name": "ABC Foods S.A.L.", "headquarters_country": "Lebanon"}).json()["id"]
    company = db.get(Company, company_id)
    company.legal_name = "ABC Foods Industries SAL"
    db.commit()
    assert planner.aliases(db, company) == ["ABC Foods Industries SAL", "ABC Foods Industries", "ABC Foods S.A.L.",
                                            "ABC Foods"]
    bilingual = Company(name="Laiterie Massabki - ألبان مسابكي", normalized_name="laiterie massabki")
    db.add(bilingual)
    db.flush()
    assert set(planner.aliases(db, bilingual)) >= {"Laiterie Massabki", "ألبان مسابكي"}
    generic = Company(name="Bank", normalized_name="bank")
    db.add(generic)
    db.flush()
    assert planner.aliases(db, generic) == []  # too generic to identify anything: no research at all
    db.add(CompanyPerson(company_id=company_id, person_id=_person(db, "Michel Haddad"), job_title="CEO",
                         department="executive", confidence=90, confidence_components={"base": 90}))
    db.commit()
    plan = planner.plan(db, company, max_queries=8, quotes=True)
    assert plan.missing[:3] == ["it", "marketing", "finance"] and "executive" not in plan.missing
    assert plan.queries[0].text == '"ABC Foods Industries SAL" management team leadership'
    assert not any("CEO managing director" in q.text for q in plan.queries)  # covered: not searched again
    assert len(plan.queries) == 8


def _person(db, name: str) -> int:
    p = Person(full_name=name, normalized_name=name.lower())
    db.add(p)
    db.flush()
    return p.id


def test_source_filtering():
    for url in ("https://www.linkedin.com/in/joseph-haddad", "https://lb.linkedin.com/company/abc",
                "https://www.zoominfo.com/p/joseph", "https://www.google.com/search?q=abc",
                "https://www.bayt.com/en/job/123", "https://example.com/login"):
        assert blocked(url), url
    assert blocked("https://summit.example/speakers") is None
    assert kind_of("https://summit.example/speakers", "Summit speakers", "abc.example").category == "conference"
    assert kind_of("https://www.abc.example/report.pdf", "", "abc.example").category == "company_document"
    assert kind_of("https://lebanon-directory.example/companies/abc", "profile", None).tier == "D"


def test_brave_provider_uses_the_api_and_never_leaks_its_key():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(url=str(request.url), token=request.headers.get("X-Subscription-Token"))
        return httpx.Response(200, json={"web": {"results": [
            {"title": "<strong>ABC Foods</strong> board", "url": "https://ali.example/board",
             "description": "Board of <strong>ABC</strong>", "page_age": "2026-01-02T00:00:00"},
            {"title": "x", "url": "javascript:alert(1)"}]}})

    brave = BraveSearchProvider("secret-key-123", timeout=5, min_interval=0, transport=httpx.MockTransport(handler))
    results = brave.search('"ABC Foods" board', limit=5)
    assert seen["url"].startswith("https://api.search.brave.com/res/v1/web/search?q=") and seen["token"] == \
        "secret-key-123"
    assert [(r.title, r.url, r.domain, r.published) for r in results] == [
        ("ABC Foods board", "https://ali.example/board", "ali.example", "2026-01-02T00:00:00")]
    failing = BraveSearchProvider("secret-key-123", timeout=5, min_interval=0,
                                  transport=httpx.MockTransport(lambda r: httpx.Response(429)))
    with pytest.raises(search.SearchError) as exc:
        failing.search("x", limit=1)
    assert "secret" not in str(exc.value)


# ---- the external sources, end to end ------------------------------------------------------------------------------


def test_people_from_public_sources(client_for, db, web, monkeypatch):
    agent, _ = client_for(UserRole.SALES_AGENT)
    monkeypatch.setattr(get_settings(), "external_results_per_query", 10)
    full_web(web)
    company_id = abc(agent, web)
    people = research(agent, company_id)
    found = roles(db, company_id)
    # Each person of ABC Foods, with the role their own entry states, from the source that states it.
    # (the annual report's "Chief Executive Officer" and the news' "CEO" are one role: CEO)
    assert set(found) == {"Joseph Haddad | IT Director", "Joseph Haddad | CIO", "Hana Fares | Procurement Manager",
                          "Michel Haddad | Chief Executive Officer", "Rita Saba | Chief Financial Officer",
                          "Nadim Aoun | Sales Director", "Fadi Salem | Procurement Manager"}
    names = {p.full_name for p in db.scalars(select(Person))}
    # Never: speakers of other companies, the group's people, vague mentions, the directory alone.
    assert not names & {"Rami Khoury", "Karim Nassar", "Sami Rizk", "Elie Matar", "Lina Saab"}
    assert found["Joseph Haddad | IT Director"].person_id == found["Joseph Haddad | CIO"].person_id  # one person
    # Recency: a 2019 programme is history, not a current role; a dated current page is current.
    assert found["Nadim Aoun | Sales Director"].employment_status == "unknown"
    assert found["Michel Haddad | Chief Executive Officer"].employment_status == "current"
    # A directory alone never makes a credible current employee.
    directory = found["Fadi Salem | Procurement Manager"]
    assert directory.confidence < 50 and directory.employment_status != "current"
    # PDF evidence keeps the document and its page.
    pdf = db.scalar(select(Evidence).join(CompanyPerson).join(Person).where(
        Person.full_name == "Hana Fares", Evidence.company_person_id.is_not(None)))
    assert pdf.structured_value["page"] == 2 and pdf.excerpt.startswith("Page 2:")
    assert db.get(Source, pdf.source_id).source_type == "conference"  # a conference programme, read as PDF
    assert db.scalar(select(ExternalDocument.doc_type).where(ExternalDocument.source_id == pdf.source_id)) == "pdf"
    # Joseph's email was published with him; the others' are PREDICTED from the pattern his address shows
    # (first.last), labelled as such, never published / verified.
    emails = {(e.email, e.status, e.provenance) for e in db.scalars(select(Email).where(Email.person_id.is_not(None)))}
    assert ("joseph.haddad@abcfoods.example", "published", "public") in emails
    assert all(status == "predicted" and provenance == "predicted" for email, status, provenance in emails
               if email != "joseph.haddad@abcfoods.example")
    assert ("michel.haddad@abcfoods.example", "predicted", "predicted") in emails
    assert count(db, Phone, Phone.person_id.is_not(None)) == 0
    # Never fetched: LinkedIn (even when a search result points to it).
    assert not any("linkedin" in r for r in web.requests)
    # The People API explains each person with source types.
    joseph = [p for p in people if p["person"]["full_name"] == "Joseph Haddad"]
    assert {s["source_type"] for p in joseph for s in p["sources"]} >= {"conference", "case_study"}
    assert next(p for p in joseph if p["is_key"])["normalized_title"] == "CIO"  # CIO ranks before IT Director
    company = db.get(Company, company_id)
    assert company.external_people_status == "completed" and company.people_coverage["source_scope"] == \
        "website + external"


def test_snippets_are_never_facts(client_for, db, web):
    agent, _ = client_for(UserRole.SALES_AGENT)
    web.sites["thin.example"] = {"/page": "<html><title>ABC Foods news</title><p>ABC Foods grows.</p></html>"}
    web.results["management"] = [hit("https://thin.example/page", "ABC Foods news",
                                     "John Haddad, IT Manager at ABC Foods, said...")]
    web.results["CIO"] = [hit("https://gone.example/page", "ABC Foods IT team", "Sara Nader, CIO at ABC Foods")]
    company_id = abc(agent, web, website=False)
    research(agent, company_id)
    assert count(db, Person) == 0  # neither the snippet nor an unreachable page makes a person


def test_similar_names_and_group_roles_do_not_cross_match(client_for, db, web):
    agent, _ = client_for(UserRole.SALES_AGENT)
    web.sites["news.example"] = {"/abc": f"""<html><head><title>ABC news</title>
        <meta property="article:published_time" content="{NOW_YEAR}-01-01"></head><body>
        <p>ABC Foodstuff CEO Tony Matar said prices will rise.</p><p>ABC Foods Group CEO Marc Daher spoke.</p>
        <p>Group CIO, ABC Foods: Omar Itani - Group CIO, ABC Foods</p></body></html>"""}
    web.results["management"] = [hit("https://news.example/abc", "ABC Foods ABC Foodstuff news")]
    company_id = abc(agent, web, website=False)
    research(agent, company_id)
    assert count(db, Person) == 0


def test_independent_sources_confirm_but_syndicated_copies_do_not(client_for, db, web, monkeypatch):
    agent, _ = client_for(UserRole.SALES_AGENT)
    monkeypatch.setattr(get_settings(), "external_results_per_query", 10)
    full_web(web)
    company_id = abc(agent, web)
    research(agent, company_id)
    ceo = roles(db, company_id)["Michel Haddad | Chief Executive Officer"]
    # the annual report + the news article + its copy: three evidence records, two independent origins
    assert count(db, Evidence, Evidence.company_person_id == ceo.id) == 3
    assert ceo.confidence_components["sources"] == 2


def test_website_and_external_people_merge_and_corrections_hold(client_for, db, web):
    agent, _ = client_for(UserRole.SALES_AGENT)
    full_web(web)
    web.sites["www.abcfoods.example"] = {"/": HOME.replace("</nav>", '<a href="/team">Team</a></nav>'),
                                         "/team": "<html><title>Team</title><h3>Rita Saba</h3><p>CFO</p></html>"}
    company_id = agent.post("/companies", json={"name": "ABC Foods", "headquarters_country": "Lebanon",
                                                "website": "https://www.abcfoods.example"}).json()["id"]
    research(agent, company_id)
    rita = [r for k, r in roles(db, company_id).items() if k.startswith("Rita Saba")]
    assert len({r.person_id for r in rita}) == 1  # the team page and the association board: one Rita Saba
    cfo = next(r for r in rita if r.job_title == "CFO")
    assert agent.patch(f"/companies/{company_id}/people/{cfo.id}", json={"employment_status": "former"}
                       ).status_code == 200
    agent.post(f"/companies/{company_id}/refresh")
    while jobs.run_next((*jobs.RESEARCH, jobs.EXTERNAL)):
        pass
    db.refresh(cfo)
    assert cfo.employment_status == "former"


# ---- budgets, early stop, failures, caches ---------------------------------------------------------------------------


def test_budget_early_stop_and_failure_isolation(client_for, db, web, monkeypatch):
    agent, _ = client_for(UserRole.SALES_AGENT)
    full_web(web)
    monkeypatch.setattr(get_settings(), "external_max_queries", 2)
    company_id = abc(agent, web)
    research(agent, company_id)
    assert len(web.queries) == 2  # the query budget
    run = db.scalar(select(func.max(func.cast(Company.id, Company.name.type)))) and None  # noqa: F841
    # Failing provider: the company's own documents are still read; the result is partial, not failed.
    web.results.clear()
    web.results["fail"] = []
    other = agent.post("/companies", json={"name": "Omega Biscuits", "headquarters_country": "Lebanon",
                                           "website": "https://www.omega.example"}).json()["id"]
    web.sites["www.omega.example"] = {"/": HOME.replace("ABC Foods", "Omega Biscuits").replace(
        "annual-report-2025.pdf", "report.pdf"), "/files/report.pdf": (REPORT.replace(b"ABC Foods", b"Omega Biscuits"),
                                                                       "application/pdf")}
    research(agent, other)
    company = db.get(Company, other)
    assert company.external_people_status == "partial" and "unavailable" in company.external_people_message
    assert "Michel Haddad | Chief Executive Officer" in roles(db, other)


def test_early_stop_when_departments_are_covered(client_for, db, web):
    agent, _ = client_for(UserRole.SALES_AGENT)
    full_web(web)
    company_id = abc(agent, web)
    for dept, title in (("executive", "CEO"), ("it", "CIO"), ("marketing", "CMO"), ("finance", "CFO"),
                        ("sales", "Sales Director"), ("operations", "COO"), ("hr", "HR Director"),
                        ("procurement", "Procurement Manager")):
        db.add(CompanyPerson(company_id=company_id, person_id=_person(db, f"Known {dept.title()}"), job_title=title,
                             department=dept, confidence=90, confidence_components={"base": 90}))
    db.commit()
    research(agent, company_id)
    assert web.queries == []  # every priority department covered: no external research at all
    assert db.get(Company, company_id).external_people_status == "not_started"


def test_documents_and_searches_are_cached_and_research_is_idempotent(client_for, db, web):
    agent, _ = client_for(UserRole.SALES_AGENT)
    full_web(web)
    company_id = abc(agent, web)
    research(agent, company_id)
    before = (count(db, Person), count(db, CompanyPerson), count(db, Evidence), count(db, Source))
    fetched, searched = len(web.requests), len(web.queries)
    external.run(db, company_id, force=True)
    assert len(web.requests) == fetched and len(web.queries) == searched  # cache: nothing fetched / searched
    assert (count(db, Person), count(db, CompanyPerson), count(db, Evidence), count(db, Source)) == before
    assert count(db, ExternalDocument, ExternalDocument.doc_type == "pdf") == 2
    assert count(db, ExternalSearchCache, ExternalSearchCache.provider == "fake") == searched


def test_company_documents_without_any_search_provider(client_for, db, web):
    agent, _ = client_for(UserRole.SALES_AGENT)
    web.provider = None
    company_id = abc(agent, web)
    research(agent, company_id)
    found = roles(db, company_id)
    assert set(found) == {"Michel Haddad | Chief Executive Officer", "Rita Saba | Chief Financial Officer"}
    report = db.scalar(select(Evidence).where(Evidence.company_person_id == found[
        "Michel Haddad | Chief Executive Officer"].id))
    assert report.structured_value["page"] == 2 and found["Rita Saba | Chief Financial Officer"].employment_status \
        == "current"
    company = db.get(Company, company_id)
    # no search API is needed: not a problem, not a warning
    assert company.external_people_status == "completed" and company.external_people_message is None


def test_an_old_company_document_is_history(client_for, db, web):
    agent, _ = client_for(UserRole.SALES_AGENT)
    web.provider = None
    old = make_pdf([["Corporate profile 2019"], ["Rita Saba - Chief Financial Officer"]], "Corporate profile 2019")
    old = old.replace(f"D:{NOW_YEAR}".encode(), b"D:2019")
    web.sites["www.abcfoods.example"] = {"/": HOME.replace("annual-report-2025.pdf", "profile-2019.pdf"),
                                         "/files/profile-2019.pdf": (old, "application/pdf")}
    company_id = agent.post("/companies", json={"name": "ABC Foods", "headquarters_country": "Lebanon",
                                                "website": "https://www.abcfoods.example"}).json()["id"]
    research(agent, company_id)
    assert roles(db, company_id)["Rita Saba | Chief Financial Officer"].employment_status == "unknown"


def test_no_people_from_public_sources(client_for, db, web):
    agent, _ = client_for(UserRole.SALES_AGENT)
    web.sites["www.quiet.example"] = {"/": "<html><title>Quiet Mills</title><p>Quiet Mills, Zahle.</p></html>"}
    company_id = agent.post("/companies", json={"name": "Quiet Mills", "headquarters_country": "Lebanon",
                                                "website": "https://www.quiet.example"}).json()["id"]
    assert research(agent, company_id) == []
    c = agent.get(f"/companies/{company_id}").json()["company"]
    assert (c["people_status"], c["external_people_status"]) == ("completed", "completed")


def test_coverage_benchmark_instrumentation(client_for, db, web):
    from scripts.people_coverage import measure

    agent, _ = client_for(UserRole.SALES_AGENT)
    full_web(web)
    company_id = abc(agent, web)
    research(agent, company_id)
    empty = agent.post("/companies", json={"name": "Nobody Ltd"}).json()["id"]
    result = measure([company_id, empty])
    assert (result["companies"], result["with_1_person"], result["useful_people_coverage_pct"]) == (2, 1, 50.0)
    assert result["department_coverage"]["it"] == 1 and result["roles_from_external_sources"] > 0
