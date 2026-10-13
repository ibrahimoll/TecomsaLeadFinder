"""Query-driven company search (Step 5.4.1): what the user types is understood (name / place / industry / domain,
English / French / Arabic), searched in LeadFinder first, then in the corpus, extracts and live sources, then on the
web (candidate domains, each website VERIFIED: name + country, never a parked page / directory / same name abroad),
creating only verified companies, learning their domains (current and historical). Formatech is one regression
case among unrelated ones; production code holds no company name. Every page and API is mocked."""

import httpx
import pytest
from sqlalchemy import func, select

from app.models import Company, CompanyDomain, CompanyLookup, ResearchRun
from app.models.enums import UserRole
from app.services import company_lookup, company_search, web_discovery
from app.services.discovery import fetch, orchestrator
from app.services.people.external.lebanon.records import Record
from app.services.query_understanding import names, parse

from .test_external_people import web  # noqa: F401  (fixture)
from .test_lebanon_sources import keep, new_company


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(orchestrator, "build_connectors", lambda country: [])
    monkeypatch.setattr(company_lookup, "_INDEX", {})
    web_discovery.Breaker.reset()


@pytest.fixture
def sites(web, monkeypatch):
    """Websites that exist (DNS resolves only for them) for web discovery: {host: html}."""
    def resolve(host):
        if host not in web.sites:
            raise fetch.FetchError("DNS", f"{host} does not resolve")
        return ["93.184.216.34"]
    monkeypatch.setattr(fetch, "resolve", resolve)
    from app.services.people.external import search
    monkeypatch.setattr(search, "provider", lambda purpose="people": None)  # the default: no licensed search API
    return web.sites


def page(title, body="", footer="") -> dict:
    return {"/": f"<html><head><title>{title}</title></head><body><h1>{title.split('|')[0]}</h1><p>{body}</p>"
                 f"<p>{'Our team serves clients across the region with care and experience. ' * 3}</p>"
                 f"<footer>{footer}</footer></body></html>"}


def lookup(client, q, **kw) -> dict:
    response = client.post("/companies/lookup", json={"q": q, "country": "Lebanon", **kw})
    assert response.status_code == 200, response.text
    return response.json()


def count(db, model, *where) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(model).where(*where))


# ---- query understanding -----------------------------------------------------------------------------------------


def test_free_text_queries_become_a_search_intent():
    cases = {
        "find me Formatech": (["Formatech"], None, None, None),
        "Lebanese training company Formatech": (["Formatech"], None, "Lebanon", "Training"),
        "hotel called Aleph in Byblos": (["Aleph"], "Byblos (Jbeil)", "Lebanon", "Hospitality"),
        "food distributor called XYZ in Beirut": (["XYZ"], "Beirut", "Lebanon", "Distribution"),
        "I think the company is called ABC and they distribute food in Lebanon":
            (["ABC"], None, "Lebanon", "Distribution"),
        "technology company called Zeta Soft in Dubai": (["Zeta Soft"], "Dubai", "United Arab Emirates", "Technology"),
        "شركة صناعية في بيروت اسمها الأرز": (["الأرز"], "Beirut", "Lebanon", "Manufacturing"),
        "société appelée Delta Conseil à Paris": (["Delta Conseil"], "Paris", "France", None),
        "Bank of Beirut": (["Bank of Beirut"], "Beirut", "Lebanon", "Financial Services"),
        "Hotel Albergo": (["Hotel Albergo", "Albergo"], None, None, "Hospitality"),
        "hotels in Beirut": ([], "Beirut", "Lebanon", "Hospitality"),
    }
    for query, (expected, city, country, industry) in cases.items():
        intent = parse(query)
        assert (names(intent), intent.city, intent.country, intent.industry) == (expected, city, country, industry), \
            query
    assert parse("https://www.abcfoods.com/en/about").domain == "abcfoods.com"
    assert parse("ABC Foods S.A.L.").legal_form == "SAL"
    assert parse("شركة الأرز للصناعات").language == "ar"


# ---- website verification ----------------------------------------------------------------------------------------


def test_website_verification_name_country_and_rejections(sites):
    sites["deltafoods.com.lb"] = page("Delta Foods | Home", "Food production since 1990.",
                                      "© 2026 Delta Foods SAL · +961 1 234 567 · Beirut, Lebanon")
    sites["deltafoods.com"] = page("Delta Foods Inc. | Home", "Food production in Ohio.",
                                   "© 2026 Delta Foods Inc · +1 614 555 0100 · Columbus, OH")
    sites["deltafoodz.com"] = page("Deltafoodz | Home", "Snacks.", "+961 1 999 999")
    sites["delta-foods.com"] = {"/": "<html><head><title>delta-foods.com</title></head><body>This domain is for "
                                     "sale. Buy this domain today. " + "x " * 50 + "</body></html>"}
    sites["lebanonbusiness.com"] = page("Business Directory | Find a company", "Delta Foods, ABC...", "")
    strong = web_discovery.verify("Delta Foods", "https://deltafoods.com.lb/", country="Lebanon")
    assert (strong.status, strong.reason, strong.site_name) == ("strong", "NAME_AND_COUNTRY", "Delta Foods")
    assert strong.phone.startswith("+961")
    assert web_discovery.verify("Delta Foods", "https://deltafoods.com/", country="Lebanon").reason == \
        "FOREIGN_ENTITY"  # the same name abroad is another company
    assert web_discovery.verify("Delta Foods", "https://deltafoodz.com/", country="Lebanon").reason == \
        "NAME_NOT_ON_SITE"  # a similar spelling is not the company
    assert web_discovery.verify("Delta Foods", "https://delta-foods.com/", country="Lebanon").reason == \
        "PARKED_OR_EMPTY"
    assert web_discovery.verify("Delta Foods", "https://lebanonbusiness.com/", country="Lebanon").reason == \
        "DIRECTORY"


# ---- the full search ------------------------------------------------------------------------------------------------


def test_formatech_regression_unknown_company_found_on_its_own_website(client_for, db, sites):
    agent, _ = client_for(UserRole.SALES_AGENT)
    sites["formatech.com.lb"] = page("Formatech | Training & Consulting", "Corporate training in Lebanon.",
                                     "© 2026 Formatech · Beirut · +961 1 888 777")
    monkeypatch_providers = web_discovery.providers  # the default: domain candidates, no paid search
    assert [p.key for p in monkeypatch_providers()] == ["domain_guess"]
    result = lookup(agent, "Lebanese training company Formatech")
    assert result["status"] == "created" and result["resolved_from"] == "WEB_DISCOVERY"
    company = db.get(Company, result["company"]["company_id"])
    assert (company.name, company.headquarters_country) == ("Formatech", "Lebanon")
    assert "formatech.com.lb" in company.website and company.primary_phone
    assert count(db, ResearchRun, ResearchRun.company_id == company.id) >= 1  # research queued at once
    for again in ("Formatech", "formatech.com.lb", "https://www.formatech.com.lb/en", "find me formatech"):
        second = lookup(agent, again)
        assert (second["status"], second["company"]["company_id"], second["external_used"]) == \
            ("found", company.id, False), again  # learned: a database hit now
    assert count(db, Company) == 1


@pytest.mark.parametrize("query,host,title,footer", [
    ("hotel called Aleph in Byblos", "aleph.com.lb", "Aleph Boutique Hotel | Byblos", "Jbeil, Lebanon · +961 9 540 000"),
    ("Nordic Steel Industries", "nordicsteel.com.lb", "Nordic Steel | Industries", "Zahle, Lebanon +961 8 800 800"),
    ("restaurant called Mezze Garden", "mezzegarden.com", "Mezze Garden – Lebanese Restaurant", "Hamra, Beirut"),
    ("construction company Cedar Builders", "cedarbuilders.com.lb", "Cedar Builders SAL", "Beirut +961 1 400 400"),
])
def test_unrelated_unknown_companies_across_sectors(client_for, db, sites, query, host, title, footer):
    agent, _ = client_for(UserRole.SALES_AGENT)
    sites[host] = page(title, "About us.", footer)
    result = lookup(agent, query)
    assert result["status"] == "created", result
    assert host in db.get(Company, result["company"]["company_id"]).website


def test_web_discovery_never_creates_a_foreign_or_weak_match(client_for, db, sites):
    agent, _ = client_for(UserRole.SALES_AGENT)
    sites["zetaoptics.com"] = page("Zeta Optics | US", "Optics in Texas.", "© Zeta Optics Inc · +1 512 555 0101")
    sites["zetaoptic.com.lb"] = page("Zetaoptic Lebanon", "Eyewear.", "+961 1 222 333")
    result = lookup(agent, "Zeta Optics")
    assert result["status"] in ("not_found", "ambiguous") and count(db, Company) == 0
    stored = db.scalar(select(CompanyLookup))
    assert stored.parsed["name"] == "Zeta Optics" and stored.failure_reason in ("NO_SOURCE_RESULT", "WEAK_EVIDENCE")


def test_corpus_and_website_agree_one_company_with_both_sources(client_for, db, sites):
    agent, _ = client_for(UserRole.SALES_AGENT)
    keep(db, "ministry_industry", "https://industry.example/list.xls", [
        Record(org=["Omega Plastics SAL"], identifiers={"moi_factory": "91"}, domains=["omegaplastics.com.lb"],
               facts={"city": "Zahle"}, excerpt="Omega Plastics SAL, Zahle")])
    sites["omegaplastics.com.lb"] = page("Omega Plastics", "Packaging.", "Zahle, Lebanon +961 8 111 222")
    result = lookup(agent, "Omega Plastics")
    assert result["status"] == "created" and result["resolved_from"].startswith("LOCAL_CORPUS")
    company_id = result["company"]["company_id"]
    assert lookup(agent, "omegaplastics.com.lb")["company"]["company_id"] == company_id  # the source's domain
    assert count(db, Company) == 1


def test_natural_language_finds_known_companies_with_context(client_for, db):
    agent, _ = client_for(UserRole.SALES_AGENT)
    gray = new_company(agent, "Le Gray", industry="Hospitality")
    beirut = new_company(agent, "ABC Trading", industry="Distribution")
    tripoli = new_company(agent, "ABC Trading SARL", industry="Construction")
    db.get(Company, beirut).headquarters_city, db.get(Company, tripoli).headquarters_city = "Beirut", "Tripoli"
    db.commit()
    assert lookup(agent, "hotel called Le Gray in Beirut")["company"]["company_id"] == gray
    assert lookup(agent, "find me the company called ABC Trading in Tripoli")["company"]["company_id"] == tripoli
    assert lookup(agent, "ABC Trading")["status"] == "ambiguous"  # no context: never a guess


def test_sector_routing_historical_domains_and_breakers(client_for, db, monkeypatch):
    assert "icc_register" in company_lookup.routed_sources("Insurance")
    assert "hospital_syndicate" in company_lookup.routed_sources("Healthcare")
    assert company_lookup.routed_sources(None) == set()
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = new_company(agent, "Sigma Labs", website="https://sigmalabs.com.lb")
    company = db.get(Company, company_id)
    company.website, company.domain = "https://sigmalabs.com", "sigmalabs.com"  # the company moved domain
    db.commit()
    assert {(d.domain, d.status) for d in db.scalars(select(CompanyDomain))} == {
        ("sigmalabs.com.lb", "historical"), ("sigmalabs.com", "current")}
    old = company_search.search(db, "sigmalabs.com.lb")
    assert (old[0].company.id, old[0].match_type) == (company_id, "historical_domain")
    calls = []

    def failing():
        calls.append(1)
        raise httpx.ConnectError("down")
    guarded = company_lookup._guarded("flaky", failing)
    for _ in range(3):
        with pytest.raises(httpx.ConnectError):
            guarded()
    with pytest.raises(company_lookup.BreakerOpen):
        guarded()  # open: not called again for a while
    assert len(calls) == 3


def test_foreign_country_query_uses_gleif_and_keeps_the_country(client_for, db, public_apis):
    agent, _ = client_for(UserRole.SALES_AGENT)
    public_apis.routes[("api.gleif.org", "/api/v1/lei-records")] = lambda r: httpx.Response(200, json={"data": [{
        "id": "5493000ABCDEF1234567", "attributes": {"entity": {
            "legalName": {"name": "Zeta Soft FZ-LLC"}, "legalAddress": {"city": "Dubai", "country": "AE",
                                                                        "addressLines": ["Internet City"]}}}}]})
    result = lookup(agent, "technology company called Zeta Soft in Dubai")
    assert result["status"] == "created" and result["resolved_from"] == "GLEIF"
    company = db.get(Company, result["company"]["company_id"])
    assert company.headquarters_country == "United Arab Emirates" and company.name == "Zeta Soft FZ-LLC"


def test_generic_words_and_single_words_never_open_or_create_a_company(client_for, db, sites):
    """Holdout findings: 'Center for' matched 'S.A.S Center'; 'Village' created 'The Village' while known companies
    carry the word; a sound-alike made an unrelated known school 'the same' company."""
    agent, _ = client_for(UserRole.SALES_AGENT)
    new_company(agent, "S.A.S Center", industry="Professional Services")
    new_company(agent, "Village Market", industry="Retail")
    new_company(agent, "Garden Village Resort", industry="Hospitality")
    keep(db, "ministry_industry", "https://industry.example/list.xls", [
        Record(org=["The Village"], identifiers={"moi_factory": "5"}, excerpt="The Village")])
    assert lookup(agent, "Consulting Center")["status"] != "found"
    assert lookup(agent, "Center for")["status"] != "found"
    village = lookup(agent, "Village")
    assert village["status"] == "ambiguous" and not village["created"]
    assert count(db, Company) == 3
    assert company_search.name_keys("Consulting Center") == set()


def test_country_words_inside_a_name_and_full_country_names():
    assert parse("Hôtel-Dieu de France", country="Lebanon").country == "Lebanon"  # 'de France' is its name
    assert parse("Almarai in Saudi Arabia").country == "Saudi Arabia"
    assert parse("Bank of Beirut").city == "Beirut"


def test_web_discovery_spacing_short_brands_and_gulf_sites(sites):
    assert web_discovery._names_company("Liban Lait", "Libanlait")
    assert web_discovery._names_company("Mount Lebanon Hospital University Medical Center", "Mount Lebanon Hospital")
    assert not web_discovery._names_company("Aleph Dental", "Aleph")
    assert "ibl.com.lb" in web_discovery.candidate_domains("IBL Bank", "Lebanon")
    sites["zetadairy.com"] = page("Zeta Dairy | Home", "Fresh milk.", "© 2026 Zeta Dairy · +966 11 470 0005")
    assert web_discovery.verify("Zeta Dairy", "https://zetadairy.com/", country="Saudi Arabia").status == "strong"
    assert web_discovery.verify("Zeta Dairy", "https://zetadairy.com/", country="Lebanon").reason == \
        "FOREIGN_ENTITY"  # the Saudi company is not a Lebanese one
