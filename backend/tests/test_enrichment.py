"""Company research (Step 4): queueing and freshness, website ownership, page discovery and crawl budget,
deterministic extraction (profile, contacts, locations, products / services, signals), evidence and conflicts,
re-crawl caching, failure handling, SSRF safety, and independence from discovery. Websites are mocked."""

import json
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.models import (Company, CompanyLocation, CompanyOffering, CompanySignal, CompanyWebPage, Email, Evidence,
                        Person, Phone, ResearchRun, Source)
from app.models.enums import UserRole
from app.services import jobs
from app.services.discovery import fetch
from app.services.discovery.fetch import Fetcher
from app.services.discovery.web import PoliteFetcher
from app.services.enrichment import orchestrator as enrichment
from app.services.enrichment.extract import Context, extract, social_profile
from app.services.enrichment.pages import candidate_links, classify, parse

ORG = {"@context": "https://schema.org", "@type": "Organization", "name": "Crown Flour Mills",
       "legalName": "Crown Flour Mills S.A.L.", "foundingDate": "1994", "telephone": "+961 1 234 567",
       "numberOfEmployees": {"@type": "QuantitativeValue", "minValue": 200, "maxValue": 500},
       "sameAs": ["https://www.facebook.com/crownflourmills", "https://www.linkedin.com/company/crown-flour-mills"],
       "address": {"@type": "PostalAddress", "streetAddress": "Industrial Zone, Main Road", "addressLocality": "Zahle"}}


def home(org: dict = ORG) -> str:
    return f"""<html lang="en"><head><title>Crown Flour Mills | Quality flour</title>
<meta name="description" content="Crown Flour Mills produces bread, pastry and industrial flour for bakeries in Lebanon.">
<script type="application/ld+json">{json.dumps(org)}</script>
<script src="https://cdn.shopify.com/s/files/theme.js"></script></head><body>
<nav><a href="/about-us">About us</a><a href="/products">Products</a><a href="/products/bread-flour">Bread Flour</a>
<a href="/products/pastry-flour">Pastry Flour</a><a href="/services">Services</a><a href="/contact">Contact</a>
<a href="/careers">Careers</a><a href="/news">News</a><a href="/team">Our team</a><a href="/privacy">Privacy</a>
<a href="/files/brochure.pdf">Brochure</a><a href="https://partner.example/">Partner</a></nav>
<div><p>We manufacture flour in our factory in the Bekaa and export to 12 countries.</p>
<p>Fast delivery to bakeries across Lebanon.</p></div>
<footer><p>Tel: 01 234 567 | Fax: 01 234 568</p><a href="mailto:info@crownmills.example">info@crownmills.example</a>
<p>Write to john.smith@crownmills.example</p>
<a href="https://www.facebook.com/sharer/sharer.php?u=x">Share</a><a href="https://instagram.com/crownmills/">Instagram</a>
<a href="https://wa.me/96170123456">WhatsApp</a><p>© 2026 Crown Flour Mills S.A.L. All rights reserved.</p></footer>
</body></html>"""


SITE = {
    "/": home(),
    "/about-us": """<html><title>About Crown</title><body><nav><a href="/contact">Contact</a></nav>
<h1>About us</h1><p>Founded in 1996, Crown Flour Mills is a family business. We operate three factories and employ
more than 300 employees across Lebanon, supplying bakeries and industrial customers.</p></body></html>""",
    "/products": """<html><title>Products</title><body><h1>Our products</h1><h2>Bread Flour</h2><h2>Pastry Flour</h2>
<h2>Industrial Flour</h2><h2>Newsletter</h2></body></html>""",
    "/services": """<html><title>Services</title><body><h2>Bulk Distribution</h2><h2>Private Label Manufacturing</h2>
</body></html>""",
    "/contact": """<html><title>Contact us</title><body><h2>Contact</h2><h3>Zahle Factory</h3>
<p>Industrial Zone, Main Road, Zahle, Lebanon - Tel: <a href="tel:+9618123456">08 123 456</a></p>
<h3>Beirut Showroom</h3><p>Hamra Street, Sadat Building, Beirut</p>
<p>Sales: <a href="mailto:sales@crownmills.example">sales@crownmills.example</a></p><h2>Newsletter</h2></body></html>""",
    "/careers": """<html><title>Careers</title><body><h1>Join us</h1><h3>Sales Representative</h3>
<h3>IT Support Specialist</h3></body></html>""",
    "/news": """<html><title>News</title><body><h3>Crown opens new factory in the Bekaa</h3>
<h3>Partnership with Lebanese bakeries</h3></body></html>""",
    "/team": """<html><title>Our team</title><body><h3>John Smith</h3><p>Chief Executive Officer</p></body></html>""",
}


@pytest.fixture
def site(monkeypatch):
    """Websites served from {host: {path: html | bytes | (status, headers) | Exception}}; unknown hosts are down."""
    sites: dict[str, dict] = {}
    requests: list[str] = []
    monkeypatch.setattr(fetch, "resolve", lambda host: ["10.0.0.5"] if host.endswith(".internal")
                        else ["93.184.216.34"])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path != "/robots.txt":
            requests.append(f"{request.url.host}{request.url.path}")
        pages = sites.get(request.url.host)
        if pages is None:
            raise httpx.ConnectError("unreachable")
        body = pages.get(request.url.path)
        if isinstance(body, Exception):
            raise body
        if isinstance(body, tuple):  # (status, headers) or (status, headers, body)
            return httpx.Response(body[0], headers=body[1], content=body[2] if len(body) > 2 else b"")
        if isinstance(body, bytes):
            return httpx.Response(200, content=body, headers={"content-type": "text/html"})
        if body is None:
            return httpx.Response(404, text="not found", headers={"content-type": "text/html"})
        return httpx.Response(200, text=body, headers={"content-type": "text/html; charset=utf-8"})

    monkeypatch.setattr(enrichment, "website_fetcher", lambda: PoliteFetcher(
        Fetcher(max_bytes=200_000, timeout=5, transport=httpx.MockTransport(handler)), min_interval=0, retries=0))
    from app.services.people.external import documents  # documents linked from the sites: the same mocked web

    monkeypatch.setattr(documents, "fetcher", lambda pdf: PoliteFetcher(
        Fetcher(max_bytes=2_000_000, timeout=5, transport=httpx.MockTransport(handler), accept_pdf=pdf),
        min_interval=0, retries=0))
    return SimpleNamespace(sites=sites, requests=requests)


def new_company(client, name="Crown Flour Mills", website="https://www.crownmills.example", **kw) -> int:
    response = client.post("/companies", json={"name": name, "website": website, "industry": "Food Manufacturing",
                                               "headquarters_country": "Lebanon", "headquarters_city": "Zahle", **kw})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def research(client, company_id: int) -> dict:
    client.get(f"/companies/{company_id}")  # opening it queues the research (people discovery follows)
    while jobs.run_next(jobs.RESEARCH):
        pass
    return client.get(f"/companies/{company_id}").json()


def count(db, model, *where) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(model).where(*where))


# ---- queueing, freshness, refresh -------------------------------------------------------------------------------


def test_opening_a_company_queues_research_once_and_fresh_research_is_not_repeated(client_for, db, site):
    agent, _ = client_for(UserRole.SALES_AGENT)
    site.sites["www.crownmills.example"] = SITE
    company_id = new_company(agent)
    opened = agent.get(f"/companies/{company_id}").json()
    assert opened["company"]["enrichment_status"] == "queued"  # returned at once, research runs in background
    agent.get(f"/companies/{company_id}")  # opened again while queued: still one job
    run = db.scalar(select(ResearchRun).where(ResearchRun.company_id == company_id))
    assert count(db, ResearchRun, ResearchRun.research_type == "company_enrichment") == 1 and (run.research_type, run.priority) == ("company_enrichment", enrichment.OPENED_NO_PEOPLE)  # nobody known yet: first
    assert not jobs.run_next((jobs.DISCOVERY,))  # discovery lanes never take research jobs
    done = research(agent, company_id)
    assert done["company"]["enrichment_status"] == "completed" and done["company"]["last_enriched_at"]
    research(agent, company_id)  # fresh: opening it again does not research it again
    assert count(db, ResearchRun, ResearchRun.research_type == "company_enrichment") == 1


def test_manual_refresh_queues_research_even_when_fresh(client_for, db, site):
    agent, _ = client_for(UserRole.SALES_AGENT)
    site.sites["www.crownmills.example"] = SITE
    company_id = new_company(agent)
    research(agent, company_id)
    refreshed = agent.post(f"/companies/{company_id}/refresh")
    assert refreshed.status_code == 202 and refreshed.json()["enrichment_status"] == "queued"
    assert count(db, ResearchRun, ResearchRun.research_type == "company_enrichment") == 2
    # Research that crashed or was interrupted is retried later, not on every page view.
    interrupted = db.get(Company, company_id)
    interrupted.enrichment_status, interrupted.enrichment_version = "partial", None
    db.commit()
    jobs.run_next((jobs.ENRICHMENT,))
    db.refresh(interrupted)
    interrupted.enrichment_status, interrupted.enrichment_version = "partial", None
    db.commit()
    agent.get(f"/companies/{company_id}")
    assert count(db, ResearchRun, ResearchRun.research_type == "company_enrichment") == 2
    no_site = new_company(agent, name="Offline Bakery", website=None)
    assert agent.post(f"/companies/{no_site}/refresh").status_code == 422
    assert agent.get(f"/companies/{no_site}").json()["company"]["enrichment_status"] == "not_started"


# ---- the full research of one website ----------------------------------------------------------------------------


def test_research_of_a_company_website(client_for, db, site):
    agent, _ = client_for(UserRole.SALES_AGENT)
    site.sites["www.crownmills.example"] = SITE
    company_id = new_company(agent)
    detail = research(agent, company_id)
    c = detail["company"]
    # Ownership: the name is in the title and the domain.
    assert c["enrichment_status"] == "completed" and c["website_confidence"] >= 60 and c["domain"] == "crownmills.example"
    # Business profile: structured data beats running text; the disagreement is kept, not hidden.
    assert c["legal_name"] == "Crown Flour Mills S.A.L." and c["founded_year"] == 1994
    assert c["description"].startswith("Crown Flour Mills produces bread")
    assert (c["employee_count_min"], c["employee_count_max"]) == (200, 500)
    founded = next(x for x in detail["conflicts"] if x["field"] == "founded_year")
    assert [v["value"] for v in founded["values"]] == ["1994", "1996"]
    # Contacts: company level only (never a person's address), fax excluded, WhatsApp only when published.
    phones = {(p["normalized_phone"], p["phone_type"]) for p in detail["phones"]}
    assert phones == {("+9611234567", "landline"), ("+9618123456", "landline"), ("+96170123456", "whatsapp")}
    emails = {(e["email"], e["purpose"]) for e in detail["emails"]}
    assert emails == {("info@crownmills.example", "info"), ("sales@crownmills.example", "sales")}
    # Social company pages only (no share button), never fetched.
    assert (c["facebook_url"], c["linkedin_url"], c["instagram_url"]) == (
        "https://www.facebook.com/crownflourmills", "https://www.linkedin.com/company/crown-flour-mills",
        "https://www.instagram.com/crownmills")
    # Locations: the structured address and the contact page's are the same factory; the showroom is new.
    places = {(loc["city"], loc["location_type"]) for loc in detail["locations"]}
    assert places == {("Zahle", "factory"), ("Beirut", "showroom")}
    # Products / services: categories, not site furniture ("Newsletter" is a heading on several pages).
    offerings = {(o["kind"], o["raw_name"]) for o in detail["offerings"]}
    assert {("category", "Bread Flour"), ("product", "Industrial Flour"), ("service", "Bulk Distribution"),
            ("service", "Private Label Manufacturing")} <= offerings
    assert not any(name == "Newsletter" for _, name in offerings)
    # Operational signals, technology, hiring and news.
    signals = {(s["signal_type"], s["signal_value"]) for s in detail["signals"]}
    assert {("manufacturing", None), ("factory", None), ("factory", "3"), ("exporting", None), ("delivery", None),
            ("technology", "Shopify"), ("active_careers_page", None), ("job_openings", "2"),
            ("hiring_department", "sales"), ("hiring_department", "it"), ("customer_support", "WhatsApp")} <= signals
    assert {s for s, _ in signals} >= {"news_new_factory", "news_partnership"}
    assert "manufacturing" in detail["overview"] and "Crown Flour Mills is a food manufacturing company" in detail[
        "overview"]
    # Pages: budgeted, same site only, no files / legal pages; the team page is stored but no people extracted.
    fetched = {r for r in site.requests if r.startswith("www.crownmills.example")}
    assert not any(p.endswith(("/privacy", ".pdf")) for p in fetched) and not any("partner" in r for r in site.requests)
    # The team page is stored by company research; its people come from people discovery (Step 5) only, and a
    # person's address is never kept as a company contact.
    assert count(db, CompanyWebPage, CompanyWebPage.page_type == "team") == 1
    assert [p.full_name for p in db.scalars(select(Person))] == ["John Smith"]
    assert not db.scalar(select(Email.id).where(Email.person_id.is_(None), Email.email.ilike("%john%")))
    # Provenance: a source per page, every fact with its excerpt.
    about = next(s for s in detail["sources"] if s["page_type"] == "about")
    assert about["name"] == "Official website · About page" and "founded_year" in about["facts"]
    factories = db.scalar(select(Evidence).where(Evidence.company_id == company_id,
                                                 Evidence.field_name == "factory_count"))
    assert factories.extracted_value == "3" and "three factories" in factories.excerpt
    assert db.get(Source, factories.source_id).url.endswith("/about-us")


def test_research_never_overwrites_values_a_person_entered(client_for, db, site):
    agent, _ = client_for(UserRole.SALES_AGENT)
    site.sites["www.crownmills.example"] = SITE
    company_id = new_company(agent, founded_year=1990, description="Typed in by the sales team.")
    c = research(agent, company_id)["company"]
    assert (c["founded_year"], c["description"]) == (1990, "Typed in by the sales team.")
    assert c["legal_name"] == "Crown Flour Mills S.A.L."


# ---- caching: unchanged pages add nothing, changed pages are re-read -------------------------------------------------


def test_recrawl_unchanged_adds_nothing_and_changed_content_is_reprocessed(client_for, db, site):
    agent, _ = client_for(UserRole.SALES_AGENT)
    site.sites["www.crownmills.example"] = dict(SITE)
    company_id = new_company(agent)
    research(agent, company_id)
    before = (count(db, Evidence), count(db, Source), count(db, CompanyLocation), count(db, Phone),
              count(db, CompanySignal), count(db, CompanyOffering))
    agent.post(f"/companies/{company_id}/refresh")
    research(agent, company_id)
    assert (count(db, Evidence), count(db, Source), count(db, CompanyLocation), count(db, Phone),
            count(db, CompanySignal), count(db, CompanyOffering)) == before
    site.sites["www.crownmills.example"]["/"] = home({**ORG, "foundingDate": "1993"})  # the site changed
    agent.post(f"/companies/{company_id}/refresh")
    c = research(agent, company_id)["company"]
    assert count(db, Source) == before[1] + 1 and c["founded_year"] == 1993  # same confidence: the newest wins


# ---- crawl budget, failures, timeouts, SSRF -------------------------------------------------------------------------


def test_crawl_budget_is_enforced(client_for, db, site, monkeypatch):
    agent, _ = client_for(UserRole.SALES_AGENT)
    monkeypatch.setattr(get_settings(), "enrichment_page_budget", 3)
    site.sites["www.crownmills.example"] = SITE
    agent.get(f"/companies/{new_company(agent)}")
    while jobs.run_next((jobs.ENRICHMENT,)):  # company research only (people discovery may read one team page)
        pass
    assert len(site.requests) == 3
    assert [r.split("/", 1)[1] for r in site.requests[1:]] == ["contact", "about-us"]  # most useful pages first


@pytest.mark.parametrize("pages, message", [
    (None, "could not be reached (connect)"),
    ({"/": httpx.ReadTimeout("slow")}, "could not be reached (timeout)"),
    ({"/": (500, {})}, "answered HTTP 500"),
    ({"/": "<html><title>crownmills.example - This domain is for sale</title></html>"}, "parked"),
    ({"/": "<html><title>Totally unrelated shop</title><p>Shoes and bags.</p></html>"}, "could not be confirmed"),
    ({"/": (302, {"location": "http://metadata.internal/latest"})}, "could not be reached (blocked_address)"),
])
def test_a_bad_website_gives_partial_research_never_a_failed_company(client_for, db, site, pages, message):
    agent, _ = client_for(UserRole.SALES_AGENT)
    if pages is not None:
        site.sites["www.crownmills.example"] = pages
    company_id = new_company(agent)
    c = research(agent, company_id)["company"]
    assert c["enrichment_status"] == "partial" and message in c["enrichment_message"]
    assert c["last_verified_at"] is None and count(db, Evidence, Evidence.company_id == company_id) == 0
    assert not any("internal" in r for r in site.requests)  # never a request to an internal address


def test_private_addresses_are_never_fetched(client_for, db, site):
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = new_company(agent, website="http://intranet.internal/")
    c = research(agent, company_id)["company"]
    assert c["enrichment_status"] == "partial" and "blocked_address" in c["enrichment_message"]
    assert site.requests == []


# ---- locations ----------------------------------------------------------------------------------------------------


def test_locations_merge_only_clear_matches(client_for, db, site):
    agent, _ = client_for(UserRole.SALES_AGENT)
    site.sites["www.crownmills.example"] = SITE
    company_id = new_company(agent)
    db.add(CompanyLocation(company_id=company_id, country="Lebanon", city="Zahle", address="Industrial Zone, Main Road",
                           latitude=33.85, longitude=35.90))  # e.g. found by discovery
    db.commit()
    research(agent, company_id)
    rows = db.scalars(select(CompanyLocation).where(CompanyLocation.company_id == company_id)).all()
    assert len(rows) == 2  # the factory merged into the known place; the Beirut showroom added
    zahle = next(r for r in rows if r.city == "Zahle")
    assert (zahle.location_type, zahle.phone, zahle.name) == ("factory", "+9618123456", "Zahle Factory")


# ---- language, discovery independence, responsiveness ---------------------------------------------------------------


def test_arabic_page_in_a_legacy_encoding(client_for, db, site):
    agent, _ = client_for(UserRole.SALES_AGENT)
    page = ('<html lang="ar"><head><meta charset="windows-1256"><title>مطاحن التاج</title></head><body>'
            '<p>مطاحن التاج شركة لبنانية تأسست عام 1985 وتنتج الطحين في مصنعنا في زحلة.</p>'
            '<p>هاتف: 08 765 432</p></body></html>').encode("windows-1256")
    site.sites["www.altaj.example"] = {"/": page}
    company_id = new_company(agent, name="مطاحن التاج", website="https://www.altaj.example")
    detail = research(agent, company_id)
    assert detail["company"]["founded_year"] == 1985 and detail["company"]["enrichment_status"] == "completed"
    assert [p["normalized_phone"] for p in detail["phones"]] == ["+9618765432"]
    stored = db.scalar(select(CompanyWebPage).where(CompanyWebPage.company_id == company_id))
    assert "مطاحن التاج" in stored.title and {"manufacturing", "factory"} <= {
        s["signal_type"] for s in detail["signals"]}


def test_search_results_never_wait_for_research(client_for, db, site, monkeypatch):
    from tests.test_discovery import FakeConnector, cand, config
    from app.services.discovery import orchestrator

    agent, _ = client_for(UserRole.SALES_AGENT)
    site.sites["www.crownmills.example"] = SITE
    monkeypatch.setattr(orchestrator, "build_connectors", lambda country: [FakeConnector(config("gov"), lambda: [
        cand("Crown Flour Mills", website="https://www.crownmills.example")])])
    created = agent.post("/lead-searches", json={"country": "Lebanon", "city": "Beirut",
                                                 "industry": "Food Manufacturing", "requested_count": 1}).json()
    assert jobs.run_next((jobs.DISCOVERY,))
    found = agent.get(f"/lead-searches/{created['id']}").json()
    assert (found["status"], found["enrichment_status"]) == ("completed", "running")
    run = db.scalar(select(ResearchRun).where(ResearchRun.research_type == "company_enrichment"))
    assert (run.priority, run.search_id) == (enrichment.SEARCH, created["id"])
    while jobs.run_next():
        pass
    assert agent.get(f"/lead-searches/{created['id']}").json()["enrichment_status"] == "completed"


def test_the_api_stays_responsive_while_a_company_is_researched(client_for, db, site, monkeypatch):
    agent, _ = client_for(UserRole.SALES_AGENT)
    slow = {path: html for path, html in SITE.items()}
    site.sites["www.crownmills.example"] = slow
    company_id = new_company(agent)
    original = enrichment.website_fetcher

    def slow_fetcher():
        fetcher = original()
        get = fetcher.get

        def delayed(url):
            time.sleep(0.3)
            return get(url)
        fetcher.get = delayed
        return fetcher
    monkeypatch.setattr(enrichment, "website_fetcher", slow_fetcher)
    agent.get(f"/companies/{company_id}")
    worker = threading.Thread(target=lambda: jobs.run_next((jobs.ENRICHMENT,)))
    worker.start()
    time.sleep(0.4)
    started = time.monotonic()
    status = agent.get(f"/companies/{company_id}").json()["company"]["enrichment_status"]
    assert agent.get("/companies").status_code == 200 and time.monotonic() - started < 1.0
    assert status == "researching"  # visible while it runs
    worker.join(30)
    assert agent.get(f"/companies/{company_id}").json()["company"]["enrichment_status"] == "completed"


# ---- extractors, directly -------------------------------------------------------------------------------------------


def test_page_classification_and_discovery():
    assert [classify(u) for u in ("https://a.example/", "https://a.example/en/about-us", "https://a.example/contact-us",
                                  "https://a.example/our-branches", "https://a.example/products/flour",
                                  "https://a.example/careers", "https://a.example/blog/x", "https://a.example/team",
                                  "https://a.example/من-نحن")] == [
        "homepage", "about", "contact", "locations", "products", "careers", "news", "team", "about"]
    # Shop category slugs that merely contain a page word are not those pages (real cases).
    assert {classify(f"https://shop.example/{slug}") for slug in ("cpu-contact-brackets", "presentation-remotes",
                                                                   "business-desktops", "office-productivity")} == {
        "other"}
    from app.services.enrichment.extract import location_type
    assert location_type("Ideal for business or leisure") is None
    doc = parse(SITE["/"], "https://www.crownmills.example/")
    found = [(u.rsplit("/", 1)[-1], kind) for _, u, kind in candidate_links(doc, "crownmills.example")]
    assert found[:2] == [("contact", "contact"), ("about-us", "about")]
    assert not any(u in ("privacy", "brochure.pdf", "") for u, _ in found)


@pytest.mark.parametrize("url, expected", [
    ("https://www.facebook.com/crownflourmills/", ("facebook", "https://www.facebook.com/crownflourmills")),
    ("https://facebook.com/sharer/sharer.php?u=x", None),
    ("https://www.linkedin.com/company/crown/about/", ("linkedin", "https://www.linkedin.com/company/crown")),
    ("https://www.linkedin.com/in/john-smith", None),  # a person's profile: never stored
    ("https://www.youtube.com/@crown", ("youtube", "https://www.youtube.com/@crown")),
    ("https://twitter.com/intent/tweet?text=x", None),
    ("https://x.com/crown", ("twitter", "https://x.com/crown")),
    ("https://www.tiktok.com/@crown", ("tiktok", "https://www.tiktok.com/@crown")),
])
def test_social_profiles(url, expected):
    assert social_profile(url) == expected


def test_negated_and_unrelated_text_is_not_a_signal():
    doc = parse("<p>We do not export. Our hotel partners love our bread.</p>", "https://a.example/about")
    signals = {f.name for f in extract(doc, "about", Context("Bread Co", "LB", "Lebanon", "a.example"))
               if f.kind == "signal"}
    assert "exporting" not in signals


def test_the_company_a_user_opens_is_researched_before_search_results(client_for, db, site):
    agent, _ = client_for(UserRole.SALES_AGENT)
    site.sites["www.crownmills.example"] = SITE
    site.sites["www.other.example"] = {"/": "<html><title>Other Foods</title><p>Other Foods, Zahle.</p></html>"}
    queued_by_search = db.get(Company, new_company(agent, name="Other Foods", website="https://www.other.example"))
    enrichment.request(db, queued_by_search, enrichment.SEARCH)
    db.commit()
    opened = new_company(agent)
    agent.get(f"/companies/{opened}")  # queued later, but first in line
    assert jobs.run_next((jobs.ENRICHMENT,))
    db.expire_all()
    assert db.get(Company, opened).enrichment_status == "completed"
    assert db.get(Company, queued_by_search.id).enrichment_status == "queued"


# ---- a company without a website: found on the web first -----------------------------------------------------------


def test_a_company_without_a_website_gets_it_from_a_web_search_when_a_person_asks(client_for, db, site, monkeypatch):
    """Opened by a person: its website is looked for on the web (verified on the site), then researched as usual.
    Background research never searches the web."""
    from app.services import web_discovery
    from app.services.people.external import search

    class Engine:
        key, supports_quotes, queries = "fake", True, []

        def search(self, query, *, limit, country=None, language=None):
            Engine.queries.append(query)
            return [search.SearchResult("Crown Flour Mills - Home | Facebook", "https://www.facebook.com/crownmills",
                                        "", "www.facebook.com"),
                    search.SearchResult("Crown Flour Mills | Bread and flour", "https://www.crownmills.example/about",
                                        "", "www.crownmills.example")]

    monkeypatch.setattr(search, "provider", lambda purpose="people": Engine() if purpose == "company" else None)
    monkeypatch.setattr(web_discovery, "providers", lambda: [web_discovery.LicensedSearchDiscovery(Engine())])
    site.sites["www.crownmills.example"] = SITE
    agent, _ = client_for(UserRole.SALES_AGENT)
    cid = new_company(agent, website=None)
    company = db.get(Company, cid)
    assert enrichment.request(db, company, enrichment.STALE) is False and not Engine.queries  # background: never
    db.rollback()
    detail = research(agent, cid)["company"]
    assert detail["website"].startswith("https://www.crownmills.example")
    assert detail["facebook_url"] == "https://www.facebook.com/crownflourmills"  # the site's own link wins
    assert "Crown Flour Mills produces bread" in (detail["description"] or "")  # the found site was then read
    assert any(e.email == "info@crownmills.example" for e in db.scalars(select(Email).where(Email.company_id == cid)))


def test_no_website_found_is_partial_and_not_searched_again_on_every_view(client_for, db, site, monkeypatch):
    from app.services import web_discovery
    from app.services.people.external import search

    calls = []

    class Nothing:
        key, supports_quotes = "fake", True

        def search(self, query, *, limit, country=None, language=None):
            calls.append(query)
            return [search.SearchResult("Unfindable Shop (@unfindableshop) • Instagram", "https://www.instagram.com/"
                                        "unfindableshop/", "", "www.instagram.com"),
                    search.SearchResult("Unfindable Shop | sweets | Instagram", "https://www.instagram.com/"
                                        "reel/xyz/", "", "www.instagram.com")]

    monkeypatch.setattr(search, "provider", lambda purpose="people": Nothing() if purpose == "company" else None)
    monkeypatch.setattr(web_discovery, "providers", lambda: [web_discovery.LicensedSearchDiscovery(Nothing())])
    agent, _ = client_for(UserRole.SALES_AGENT)
    cid = new_company(agent, name="Unfindable Shop", website=None)
    detail = research(agent, cid)["company"]
    assert detail["enrichment_status"] == "partial" and "No website" in detail["enrichment_message"]
    assert detail["instagram_url"] == "https://www.instagram.com/unfindableshop/"  # its page, never a reel
    searched = len(calls)
    research(agent, cid)  # opened again: fresh, not searched again
    assert searched == 1 and len(calls) == searched
