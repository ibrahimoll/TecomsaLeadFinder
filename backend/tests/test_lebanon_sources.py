"""Step 5.1 zero-cost people sources: the Lebanon source pack (ABL, ICC, Ministry of Industry, IDAL, RDCL, ALI,
official files), Common Crawl and Wikidata, the source router, ingest-once / change detection, strict company matching
and the Step 5 rules (status, confidence, evidence, corrections). Every web page and public API is mocked."""

import gzip
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models import (Company, CompanyIdentifier, CompanyPerson, Email, Evidence, ExternalDocument, Person, Phone,
                        Source)
from app.models.enums import UserRole
from app.services.enrichment.pages import parse
from app.services.people.external import documents, orchestrator as external, search
from app.services.people.external.lebanon import commoncrawl, pack, parsers
from app.services.people.external.lebanon.records import Record, candidate, keys_of, match, org_key
from app.services.people.external.sources import blocked

from .test_external_people import count, make_pdf, research, roles, web  # noqa: F401  (fixture)

NOW = datetime.now(timezone.utc)


def new_company(client, name, *, industry=None, website=None, country="Lebanon") -> int:
    payload = {"name": name, "industry": industry, "headquarters_country": country, "website": website}
    return client.post("/companies", json={k: v for k, v in payload.items() if v}).json()["id"]


def source(key, **changes) -> pack.SourceConfig:
    base = pack.configs()[key]
    return pack.SourceConfig(**{**base.__dict__, **changes})


def keep(db, key, url, records, *, raw=None, published=None, doc_type="html"):
    """Stores one document of a source (as refresh does) and returns the row (None: unchanged)."""
    raw = raw if raw is not None else json.dumps([r.to_json() for r in records])
    return pack.store(db, pack.configs()[key], url, doc_type, raw, lambda: records, published)


def people_of(db, company_id) -> dict[str, CompanyPerson]:
    return roles(db, company_id)


# ---- no paid API ---------------------------------------------------------------------------------------------------


def test_runs_with_no_search_key_and_brave_disabled(client_for, db, monkeypatch):
    s = get_settings()
    assert s.people_search_provider == "none" and s.brave_search_api_key is None
    assert search.provider() is None  # disabled cleanly: no key needed, nothing raised
    monkeypatch.setattr(s, "people_search_provider", "brave")
    assert search.provider() is None  # even selected, Brave stays off without its (paid) key
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = new_company(agent, "Omega Hotel", industry="Hospitality")
    result = external.run(db, company_id, force=True)
    assert result["status"] == "completed" and result["message"] is None
    assert "web_search" not in result["sources_routed"]


# ---- router -----------------------------------------------------------------------------------------------------


def test_source_router_by_industry_and_irrelevant_sources_skipped(client_for, db):
    agent, _ = client_for(UserRole.SALES_AGENT)
    bank = db.get(Company, new_company(agent, "Omega Bank S.A.L.", industry="Financial Services"))
    insurer = db.get(Company, new_company(agent, "Cedar Insurance", industry="Insurance"))
    factory = db.get(Company, new_company(agent, "Zahle Dairies", industry="Food Manufacturing",
                                          website="https://www.zahledairies.example"))
    hotel = db.get(Company, new_company(agent, "Mar Mikhael Hotel", industry="Hospitality"))
    abroad = db.get(Company, new_company(agent, "Paris Bank", industry="Financial Services", country="France"))
    assert {"abl_almanac", "abl_hr"} <= set(pack.directory_sources(bank))
    assert not {"ministry_industry", "icc_register"} & set(pack.directory_sources(bank))
    assert "icc_register" in pack.directory_sources(insurer) and "abl_almanac" not in pack.directory_sources(insurer)
    assert {"ministry_industry", "ali_members", "idal_directories"} <= set(pack.directory_sources(factory))
    assert not {"abl_almanac", "icc_register", "ministry_industry"} & set(pack.directory_sources(hotel))
    assert pack.directory_sources(abroad) == []  # the Lebanon pack is for Lebanese companies
    assert "licensed_directory" not in pack.directory_sources(bank)  # disabled until licensed
    assert pack.route(factory)[-1] == "common_crawl" and "web_search" not in pack.route(factory)


# ---- company names -------------------------------------------------------------------------------------------------


def test_lebanese_company_names_legal_forms_arabic_and_french():
    assert org_key("BANQUE LIBANO-FRANÇAISE S.A.L.") == org_key("Banque Libano Francaise sal") == \
        "bank francaise libano"  # legal form dropped, French 'banque' = 'bank', word order ignored
    assert org_key("Banque Libanaise pour le Commerce") == org_key("Lebanese Bank for Commerce")
    assert org_key("Omega Trading S.A.R.L.") == org_key("Omega Trading SARL") == "omega trading"
    assert org_key("مسابكي ش.م.ل") == org_key("مسابكي ش م ل") == "مسابكي"
    assert org_key("ألبان وأجبان مسابكي") == org_key("البان واجبان مسابكي")  # hamza forms
    assert org_key("Société Générale de Banque au Liban") == org_key("Societe Generale de Banque au Liban")
    full, core, acronyms = keys_of(["Laiterie Massabki - البان وأجبان مسابكي"])
    assert {org_key("Laiterie Massabki"), org_key("البان واجبان مسابكي")} <= full
    record = Record(org=["SOCIETE GENERALE DE BANQUE AU LIBAN S.A.L. (SGBL)"])
    assert match(*keys_of(["SGBL"])[:2], None, record, keys_of(["SGBL"])[2]) == 88  # its published acronym
    assert match(*keys_of(["SNA Lebanon"])[:2], None, Record(org=["SNA SAL"]), keys_of(["SNA Lebanon"])[2]) == 80
    # a group is another entity, both ways; a vague single word identifies nothing
    assert match(*keys_of(["Omega Foods"])[:2], None, Record(org=["Omega Foods Group"])) is None
    assert match(*keys_of(["Bank"])[:2], None, Record(org=["Bank S.A.L."])) is None
    assert match(*keys_of(["Omega Foods"])[:2], "omegafoods.example",
                 Record(org=["شركة اوميغا"], domains=["omegafoods.example"])) == 92  # same website, any language


# ---- ABL ---------------------------------------------------------------------------------------------------------

ALMANAC = make_pdf([
    ["Association of Banks in Lebanon", "ALMANAC OF BANKS IN LEBANON"],
    ["OMEGA BANK S.A.L.",
     "Official List of Banks N°: 77 (1990), Commercial Registry N°: 12345 Beirut, Nationality: Lebanese",
     "FOUNDER", "Mr. Fouad Omega",
     "SHAREHOLDERS Nationality Shares in Capital", "Mr. Sami Rizk Lebanese 12%",
     "BOARD OF DIRECTORS", "Mr. Sami Rizk Chairman & General Manager", "Mrs. Nada Aoun Member",
     "SENIOR MANAGEMENT", "Mr. Karim Saad Chief Financial Officer", "Ms. Rana Hage Head of Human Resources",
     "Mr. Fadi Nassar Assistant General Manager - Chief Information Officer",
     "HEADQUARTERS Website: www.omegabank.example", "Main branch Branch Manager: Ms. Lina Haddad"],
    ["CEDAR BANK S.A.L.", "Official List of Banks N°: 12 (1960), Commercial Registry N°: 999 Beirut",
     "SENIOR MANAGEMENT", "Mr. Tony Khoury General Manager"],
    ["NILE BANK P.L.C.", "Official List of Banks N°: 90 (1975), Commercial Registry N°: 777 Beirut",
     "BOARD OF DIRECTORS", "Mr. Omar Farouk Chairman", "MANAGEMENT IN LEBANON", "Mr. Ziad Hanna Country Manager",
     "HEAD OFFICE IN EGYPT Website: www.nilebank.example"]], "Almanac")


def test_abl_almanac_pdf_people_pages_and_identity(client_for, db):
    pages, meta = documents.pdf_pages(ALMANAC, max_pages=400, max_chars=3_000_000)
    records = parsers.abl_almanac(pages)
    found = {(r.org[0], r.person, r.title, r.page) for r in records if r.person}
    assert ("OMEGA BANK S.A.L.", "Sami Rizk", "Chairman & General Manager", 2) in found
    assert ("OMEGA BANK S.A.L.", "Nada Aoun", "Board Member", 2) in found  # a board seat, not a department
    assert ("OMEGA BANK S.A.L.", "Karim Saad", "Chief Financial Officer", 2) in found
    assert ("OMEGA BANK S.A.L.", "Lina Haddad", "Branch Manager", 2) in found
    assert ("CEDAR BANK S.A.L.", "Tony Khoury", "General Manager", 3) in found
    # a foreign bank's branch: its management in Lebanon, never its head office's board (parent / subsidiary)
    assert ("NILE BANK P.L.C.", "Ziad Hanna", "Country Manager", 4) in found
    assert not any(r.person == "Omar Farouk" for r in records)
    assert not any("12%" in (r.person or "") for r in records)  # shareholders are not people of the bank
    bank = next(r for r in records if not r.person and r.org[0] == "OMEGA BANK S.A.L.")
    assert bank.identifiers == {"bdl_bank_list": "77", "registry:LB": "12345 Beirut"}
    assert bank.domains == ["omegabank.example"]

    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = new_company(agent, "Omega Bank", industry="Financial Services")
    keep(db, "abl_almanac", "https://abl.example/almanac.pdf", records, raw=ALMANAC, doc_type="pdf",
         published=NOW - timedelta(days=120))
    pack.apply(db, db.get(Company, company_id))
    people = people_of(db, company_id)
    cfo = people["Karim Saad | Chief Financial Officer"]
    assert cfo.department == "finance" and cfo.employment_status == "current" and cfo.confidence >= 50
    evidence = db.scalar(select(Evidence).where(Evidence.company_person_id == cfo.id))
    assert evidence.excerpt.startswith("Page 2: OMEGA BANK S.A.L. — Senior Management: Mr. Karim Saad")
    assert evidence.structured_value["page"] == 2
    assert people["Fadi Nassar | Assistant General Manager - Chief Information Officer"].department == "it"
    assert people["Fouad Omega | Founder"].employment_status == "unknown"  # founding is history
    assert "Tony Khoury | General Manager" not in people  # another bank of the same almanac
    assert db.scalar(select(CompanyIdentifier.value).where(CompanyIdentifier.company_id == company_id,
                                                           CompanyIdentifier.scheme == "bdl_bank_list")) == "77"


def test_abl_heads_of_hr_and_duplicate_resolution(client_for, db):
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = new_company(agent, "Omega Bank", industry="Financial Services")
    pages, _ = documents.pdf_pages(ALMANAC)
    keep(db, "abl_almanac", "https://abl.example/almanac.pdf", parsers.abl_almanac(pages), raw=ALMANAC,
         doc_type="pdf", published=NOW - timedelta(days=60))
    hr = parsers.abl_hr([{"MemberName": "OMEGA BANK S.A.L. (77)", "PersonName": "Ms. Rana Hage",
                          "MemberSite": "http://www.omegabank.example"},
                         {"MemberName": "CEDAR BANK S.A.L. (12)", "PersonName": "Mr. Elie Saab"}])
    keep(db, "abl_hr", "https://abl.example/hr", hr, published=NOW)
    pack.apply(db, db.get(Company, company_id))
    people = people_of(db, company_id)
    hr_roles = [r for k, r in people.items() if k.startswith("Rana Hage")]
    # the almanac's "Head of Human Resources" and the HR list's "Head of HR": one person, one role, two sources
    assert len(hr_roles) == 1 and hr_roles[0].normalized_title == "Head of HR"
    assert count(db, Person, Person.full_name == "Rana Hage") == 1
    assert count(db, Evidence, Evidence.company_person_id == hr_roles[0].id) == 2
    assert hr_roles[0].confidence_components["sources"] == 2
    assert not any(k.startswith("Elie Saab") for k in people)


# ---- ingest once -----------------------------------------------------------------------------------------------


def test_documents_ingested_once_reused_and_reprocessed_only_when_changed(client_for, db, web, monkeypatch):
    agent, _ = client_for(UserRole.SALES_AGENT)
    omega = new_company(agent, "Omega Bank", industry="Financial Services")
    cedar = new_company(agent, "Cedar Bank", industry="Financial Services")
    web.sites["abl.example"] = {"/almanac.pdf": (ALMANAC, "application/pdf")}
    almanac = source("abl_almanac", urls=("https://abl.example/almanac.pdf",))
    monkeypatch.setattr(pack, "configs", lambda: {"abl_almanac": almanac})
    first = pack.refresh(db)
    assert first["abl_almanac"]["documents_new"] == 1 and first["applied"]["companies_with_people"] == 2
    assert web.requests.count("abl.example/almanac.pdf") == 1  # one download for every bank
    assert "Karim Saad | Chief Financial Officer" in people_of(db, omega)
    assert "Tony Khoury | General Manager" in people_of(db, cedar)
    again = pack.refresh(db, force=True)  # same document: not parsed, not applied again
    assert again["abl_almanac"] == {"documents_unchanged": 1, "seconds": again["abl_almanac"]["seconds"]}
    assert "applied" not in again
    changed = make_pdf([["x"], ["CEDAR BANK S.A.L.", "Official List of Banks N°: 12 (1960)", "SENIOR MANAGEMENT",
                                "Mr. Tony Khoury General Manager", "Ms. Maya Rizk Chief Financial Officer"]], "Almanac")
    web.sites["abl.example"]["/almanac.pdf"] = (changed, "application/pdf")
    third = pack.refresh(db, force=True)
    assert third["abl_almanac"]["documents_changed"] == 1 and third["applied"]["companies_with_people"] >= 1
    assert "Maya Rizk | Chief Financial Officer" in people_of(db, cedar)
    row = db.scalar(select(ExternalDocument).where(ExternalDocument.url == "https://abl.example/almanac.pdf"))
    assert row.metadata_["version"] == 2


# ---- ICC -------------------------------------------------------------------------------------------------------

def icc_html(entries, pages=1) -> str:
    context = {"state": {"loaderData": {"routes/_common.companies": {
        "companies": [{"id": i, "attributes": e} for i, e in enumerate(entries)], "maxPages": pages}}}}
    return f"<html><body><script>window.__remixContext = {json.dumps(context)};</script></body></html>"


def test_icc_register_matching_arabic_names_and_recency(client_for, db):
    recent, old = (NOW - timedelta(days=40)).date().isoformat(), "2023-01-10"
    records, pages = parsers.icc_register(icc_html([
        {"Name": "Arabia Insurance Company S.A.L | التأمين العربية ش.م.ل", "Type": "Insurance Company", "Number": "2",
         "GeneralManger": "Elie Khoury", "FinancialManager": "Abbas Sharafeddine", "Website": "https://arabia.example",
         "updatedAt": f"{recent}T08:00:00Z"},
        {"Name": "Cedar Assurance SAL", "Type": "Insurance Company", "Number": "9", "GeneralManger": "Joe Matar",
         "updatedAt": f"{old}T08:00:00Z"},
        {"Name": "Arabia Insurance Brokers s.a.r.l", "Type": "Brokerage Firm", "Number": "242",
         "GeneralManger": "Fadi Shamas", "updatedAt": f"{recent}T08:00:00Z"}], pages=51))
    assert pages == 51
    agent, _ = client_for(UserRole.SALES_AGENT)
    arabia = new_company(agent, "التأمين العربية", industry="Insurance")  # known to LeadFinder by its Arabic name
    cedar = new_company(agent, "Cedar Assurance", industry="Insurance")
    keep(db, "icc_register", "https://icc.example/companies?page=1", records)
    for company_id in (arabia, cedar):
        pack.apply(db, db.get(Company, company_id))
    people = people_of(db, arabia)
    assert set(people) == {"Elie Khoury | General Manager", "Abbas Sharafeddine | Financial Manager"}
    assert people["Abbas Sharafeddine | Financial Manager"].department == "finance"
    assert people["Elie Khoury | General Manager"].employment_status == "current"  # official, dated this year
    assert people_of(db, cedar)["Joe Matar | General Manager"].employment_status == "unknown"  # a 2023 entry
    assert db.scalar(select(CompanyIdentifier.value).where(CompanyIdentifier.company_id == arabia)) == "2"


# ---- Ministry of Industry, ALI, IDAL ------------------------------------------------------------------------------


def row(ident, name, website="", email="", production="biscuits"):
    return [ident, name, "جبل لبنان", "المتن", "الدكوانة", "", "", "", website, "", "", "", "03/111111", "", "",
            email, production]


def test_ministry_factories_owner_only_when_named(client_for, db):
    records = parsers.ministry_rows([
        row("101.0", "مصنع اوميغا لصاحبها جوزف خوري", website="www.omegafoods.example"),
        row("102.0", "شركة سيدار فودز ش.م.م", email="info@cedarfoods.example"),
        row("103.0", "السيد ميشال حداد صاحب المحل التجاري حلويات حداد"),
        row("104.0", "شركة حسن وطلال للتجارة لصاحبيها حسن وطلال شميس"),
    ], 2022)
    owners = {(r.org[0], r.person) for r in records if r.person}
    assert ("مصنع اوميغا", "جوزف خوري") in owners and ("حلويات حداد", "ميشال حداد") in owners
    assert not any(r.person and r.person.startswith("حسن") for r in records)  # "حسن وطلال": two owners, not read
    agent, _ = client_for(UserRole.SALES_AGENT)
    omega = new_company(agent, "Omega Foods", industry="Food Manufacturing", website="https://www.omegafoods.example")
    cedar = new_company(agent, "Cedar Foods", industry="Food Manufacturing", website="https://www.cedarfoods.example")
    keep(db, "ministry_industry", "https://industry.example/food-2022.xls", records, doc_type="xls",
         published=datetime(2022, 12, 31, tzinfo=timezone.utc))
    for company_id in (omega, cedar):
        pack.apply(db, db.get(Company, company_id))
    owner = people_of(db, omega)["جوزف خوري | Owner"]
    assert owner.employment_status == "unknown"  # a 2022 list: true then, not proof of today
    assert owner.department == "executive"
    assert people_of(db, cedar) == {}  # identity only (no owner named): never a person from a company field
    assert db.scalar(select(CompanyIdentifier.value).where(CompanyIdentifier.company_id == cedar,
                                                           CompanyIdentifier.scheme == "moi_factory")) == "102"


def test_ali_members_and_idal_directory(client_for, db):
    html = ('<a href="https://ali.org.lb/request-member-information/?post=3224" class="member-title"><p>Omega '
            'Pharma SAL</p><span>+</span></a>')
    ali = parsers.member_list(html)
    assert ali[0].org == ["Omega Pharma SAL"] and ali[0].identifiers == {"ali_member": "3224"}
    idal = parsers.idal([(3, "IDAL | 2013\nOmega Pharma\nCompany Profile\nEstablished in 1973...\nContact Person\n"
                             "Mr. Nazih Tabet, CEO\nE-mail Website\ninfo@omegapharma.example www.omegapharma.example\n"
                             "Cedar Labs\n• Contact Person: Rodrigue Zablith\n"
                             "• Company’s website: www.cedarlabs.example"
                          )], 2013)
    assert {(r.org[0], r.person, r.title) for r in idal if r.person} == {("Omega Pharma", "Nazih Tabet", "CEO")}
    agent, _ = client_for(UserRole.SALES_AGENT)
    omega = new_company(agent, "Omega Pharma", industry="Pharmaceutical", website="https://www.omegapharma.example")
    cedar = new_company(agent, "Cedar Labs", industry="Pharmaceutical", website="https://www.cedarlabs.example")
    keep(db, "ali_members", "https://ali.example/members?sector=pharma", ali)
    keep(db, "idal_directories", "https://idal.example/pharma-2013.pdf", idal, doc_type="pdf")
    for company_id in (omega, cedar):
        pack.apply(db, db.get(Company, company_id))
    ceo = people_of(db, omega)["Nazih Tabet | CEO"]
    assert ceo.employment_status == "unknown" and ceo.confidence < 50  # a 2013 directory: weak, not current
    assert people_of(db, cedar) == {}  # a contact person without a published title is not a person record
    assert db.scalar(select(CompanyIdentifier.value).where(CompanyIdentifier.scheme == "ali_member")) == "3224"


# ---- RDCL / association profiles ---------------------------------------------------------------------------------

PROFILE = """<html><head><title>Robert Kanaan - RDCL</title>
<meta property="article:modified_time" content="{date}"></head><body><nav>Home About</nav>
<h1>Robert Kanaan</h1><p>General Secretary</p>
<p>Robert Kanaan, with over 20 years' experience as an engineer, founded PSI Systems in 1992 where he holds since the
position of Chairman & General Manager. PSI Systems is a market leader in office printing in Lebanon.</p>
<p>He is representing PSI Systems at the Board of Directors of the Professional Computer Association as General
Secretary. He also served as President of the Lions Club and as a board member at RDCL.</p></body></html>"""
TEMPLATE = """<html><head><title>Diane Ayoub - RDCL</title></head><body><h1>Diane Ayoub</h1><p>Treasurer</p>
<p>She is an accomplished business developer. He has helped Business WordPress Theme reach new heights and enter new
markets as Chief Executive Officer of Omega Printing. Lorem ipsum dolor sit amet.</p></body></html>"""


def test_association_role_is_never_a_company_role(client_for, db):
    record = parsers.profile(parse(PROFILE.format(date=NOW.date().isoformat()), "https://rdcl.example/staff/rk/"),
                             "RDCL")
    record.published = NOW.date().isoformat()
    template = parsers.profile(parse(TEMPLATE, "https://rdcl.example/staff/da/"), "RDCL")
    assert record.person == "Robert Kanaan" and record.association_role == "General Secretary"
    agent, _ = client_for(UserRole.SALES_AGENT)
    psi = new_company(agent, "PSI Systems", industry="Technology")
    printing = new_company(agent, "Omega Printing", industry="Technology")
    keep(db, "rdcl", "https://rdcl.example/staff/rk/", [record])
    keep(db, "rdcl", "https://rdcl.example/staff/da/", [template])
    for company_id in (psi, printing):
        pack.apply(db, db.get(Company, company_id))
    people = people_of(db, psi)
    # stated FOR PSI in its biography: Chairman & GM, and founder; never his RDCL / PCA "General Secretary"
    assert set(people) == {"Robert Kanaan | Chairman & General Manager", "Robert Kanaan | Founder"}
    assert people["Robert Kanaan | Chairman & General Manager"].employment_status == "current"
    assert people["Robert Kanaan | Founder"].employment_status == "unknown"
    assert people_of(db, printing) == {}  # a theme's demo biography is not evidence


# ---- official files (Commercial Register extract), contacts -------------------------------------------------------


def test_commercial_register_is_never_queried_and_official_files_keep_published_contacts(client_for, db, web):
    report = pack.refresh(db, ["commercial_register", "licensed_directory"], force=True)
    assert report == {"commercial_register": {"skipped": "manual_file"},
                      "licensed_directory": {"skipped": "disabled"}}
    assert not web.requests  # nothing fetched from cr.justice.gov.lb (its terms forbid it) nor any directory
    with pytest.raises(ValueError):
        pack.ingest_file(db, "licensed_directory", "x.csv", "company,person\n")
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = new_company(agent, "Omega Trading", industry="Distribution")
    text = ("company,person,title,published,url,domain,registration_number,email,phone\n"
            f"Omega Trading S.A.R.L.,Rami Aoun,Managing Director,{NOW.date().isoformat()},,,2004567,"
            "rami.aoun@omegatrading.example,+9611234567\n"
            f"OMEGA TRADING SARL,Lea Nasr,Authorized Signatory,{NOW.date().isoformat()},,,,,\n")
    result = pack.ingest_file(db, "commercial_register", "extract-2026.csv", text)
    assert result["applied"]["companies_with_people"] == 1
    people = people_of(db, company_id)
    rami, lea = people["Rami Aoun | Managing Director"], people["Lea Nasr | Authorized Signatory"]
    assert rami.employment_status == "current" and rami.department == "executive"
    assert db.scalar(select(Email.email).where(Email.person_id == rami.person_id)) == "rami.aoun@omegatrading.example"
    assert db.scalar(select(Email.status).where(Email.person_id == rami.person_id)) == "published"
    assert db.scalar(select(Phone.normalized_phone).where(Phone.person_id == rami.person_id)) == "+9611234567"
    # nothing published for Lea: no e-mail pattern, no SMTP check, no phone lookup
    assert count(db, Email, Email.person_id == lea.person_id) == 0
    assert count(db, Phone, Phone.person_id == lea.person_id) == 0
    assert db.scalar(select(CompanyIdentifier.value).where(CompanyIdentifier.scheme == "registry:LB")) == "2004567"


def test_never_fetched_hosts():
    for url in ("https://www.linkedin.com/in/someone", "https://www.linkedin.com/sales/search/people",
                "https://www.google.com/search?q=omega+ceo", "https://www.bing.com/search?q=x",
                "https://search.brave.com/search?q=x", "https://duckduckgo.com/html/?q=x",
                "https://www.5index.com/company/omega", "https://5index.com.lb/members/omega"):
        assert blocked(url), url
    assert not blocked("https://www.abl.org.lb/Library/Assets/Gallery/Documents/Almanac.pdf")


def test_placeholders_never_become_people():
    record = Record(org=["Omega"], person="John Doe", title="CEO", excerpt="John Doe, CEO")
    assert candidate(record, company_id=1, source_id=1, url=None, source_type="association", quality=80,
                     match_confidence=88, stated=None, category="association", document=None) is None
    lorem = Record(org=["Omega"], person="Rana Hage", title="CEO", excerpt="Lorem ipsum dolor sit amet")
    assert candidate(lorem, company_id=1, source_id=1, url=None, source_type="association", quality=80,
                     match_confidence=88, stated=None, category="association", document=None) is None


def test_human_corrections_survive_directory_research(client_for, db):
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = new_company(agent, "Omega Bank", industry="Financial Services")
    pages, _ = documents.pdf_pages(ALMANAC)
    keep(db, "abl_almanac", "https://abl.example/almanac.pdf", parsers.abl_almanac(pages), raw=ALMANAC,
         doc_type="pdf", published=NOW)
    pack.apply(db, db.get(Company, company_id))
    cfo = people_of(db, company_id)["Karim Saad | Chief Financial Officer"]
    cfo.employment_status, cfo.is_current, cfo.department = "former", False, "finance"
    cfo.corrected_fields = ["employment_status"]
    db.commit()
    pack.apply(db, db.get(Company, company_id))  # the same current statement again
    assert people_of(db, company_id)["Karim Saad | Chief Financial Officer"].employment_status == "former"


# ---- Common Crawl ---------------------------------------------------------------------------------------------

TEAM_PAGE = """<html><head><title>Our team - Omega Tech</title></head><body><h1>Our team</h1>
<h3>John Haddad</h3><p>IT Manager</p><h3>Sarah Saad</h3><p>Marketing Director</p></body></html>"""
CLIENT_SITE = """<html><head><title>Board - Order of Engineers</title></head><body><h1>Board</h1>
<h3>Georges Doumani</h3><p>President</p></body></html>"""


def warc(url: str, html: str) -> bytes:
    body = html.encode()
    http = (b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nX-Crawler-Content-Encoding: gzip\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n")
    head = f"WARC/1.0\r\nWARC-Type: response\r\nWARC-Target-URI: {url}\r\n\r\n".encode()
    return gzip.compress(head + http + body)


def zipnum(public_apis, crawls: dict[str, list[dict]], padding: int = 0) -> None:
    """Serves Common Crawl's static URL index (collections page, cluster.idx, one gzipped index block per crawl)
    with byte ranges, as data.commoncrawl.org does; `padding` other sites' cluster lines around the block."""
    def ranged(data: bytes):
        def serve(request):
            if request.method == "HEAD":
                return httpx.Response(200, headers={"content-length": str(len(data))})
            start, _, end = request.headers.get("range", "bytes=0-").removeprefix("bytes=").partition("-")
            return httpx.Response(206, content=data[int(start):int(end or len(data) - 1) + 1])
        return serve

    base = "/cc-index/collections"
    public_apis.routes[("data.commoncrawl.org", f"{base}/index.html")] = lambda r: httpx.Response(
        200, text=" ".join(f"<a>{c}</a>" for c in crawls))
    for crawl, rows in crawls.items():
        lines = sorted(f"{commoncrawl.surt_prefix(row['url'].split('/')[2])}{row['url'].split('/', 3)[3]} "
                       f"{row['timestamp']} {json.dumps(row)}" for row in rows)
        block = gzip.compress("\n".join(lines).encode())
        first = lines[0].split(" ")[0] if lines else "zz"
        empty = gzip.compress(b"")  # other sites' index blocks: nothing of this host in them
        before = [f"aa,pad{i:06d})/ 2026\tcdx-00000.gz\t0\t{len(empty)}\t{i}" for i in range(padding)]
        after = [f"zz,pad{i:06d})/ 2026\tcdx-00000.gz\t0\t{len(empty)}\t{i}" for i in range(padding)]
        cluster = "\n".join(before + [f"{first} 2026\tcdx-00001.gz\t0\t{len(block)}\t1"] + after) + "\n"
        public_apis.routes[("data.commoncrawl.org", f"{base}/{crawl}/indexes/cluster.idx")] = ranged(cluster.encode())
        public_apis.routes[("data.commoncrawl.org", f"{base}/{crawl}/indexes/cdx-00001.gz")] = ranged(block)
        public_apis.routes[("data.commoncrawl.org", f"{base}/{crawl}/indexes/cdx-00000.gz")] = ranged(empty)


def test_common_crawl_archived_team_page(client_for, db, public_apis):
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = new_company(agent, "Omega Tech", industry="Technology", website="https://www.omegatech.example")
    blobs = {"team": warc("https://www.omegatech.example/team", TEAM_PAGE),
             "client": warc("https://client.omegatech.example/board", CLIENT_SITE)}
    lines = [{"url": "https://www.omegatech.example/team", "timestamp": "20240310120000", "digest": "A",
              "filename": "crawl-data/x.warc.gz", "offset": "0", "length": str(len(blobs["team"]))},
             {"url": "https://www.omegatech.example/team", "timestamp": "20230310120000", "digest": "A",
              "filename": "crawl-data/x.warc.gz", "offset": "0", "length": str(len(blobs["team"]))},
             {"url": "https://client.omegatech.example/board", "timestamp": "20240310120000", "digest": "B",
              "filename": "crawl-data/y.warc.gz", "offset": "0", "length": str(len(blobs["client"]))},
             {"url": "https://www.omegatech.example/products/printers", "timestamp": "20240310120000",
              "digest": "C", "filename": "crawl-data/z.warc.gz", "offset": "0", "length": "10"}]
    lines = [line | {"status": "200", "mime": "text/html"} for line in lines]
    zipnum(public_apis, {"CC-MAIN-2026-39": [], "CC-MAIN-2025-30": [], "CC-MAIN-2024-10": lines}, padding=4000)
    public_apis.routes.update({
        ("data.commoncrawl.org", "/crawl-data/x.warc.gz"): lambda r: httpx.Response(206, content=blobs["team"]),
        ("data.commoncrawl.org", "/crawl-data/y.warc.gz"): lambda r: httpx.Response(206, content=blobs["client"]),
    })
    result = external.run(db, company_id, force=True)
    # the team page (people) and the products page (company facts): same digest once, never another host
    assert result["commoncrawl_records_fetched"] == 2
    assert "data.commoncrawl.org/crawl-data/y.warc.gz" not in public_apis.requests
    people = people_of(db, company_id)
    assert set(people) == {"John Haddad | IT Manager", "Sarah Saad | Marketing Director"}
    it = people["John Haddad | IT Manager"]
    assert it.employment_status == "unknown" and it.department == "it"  # a 2024 capture: history, not today
    evidence = db.scalar(select(Evidence).where(Evidence.company_person_id == it.id))
    assert evidence.observed_at.year == 2024
    assert db.get(Source, evidence.source_id).source_type == "web_archive"
    before = (count(db, Person), count(db, CompanyPerson))
    calls = len(public_apis.requests)
    external.run(db, company_id, force=True)  # again: cached index and page, no duplicate people
    assert (count(db, Person), count(db, CompanyPerson)) == before
    assert not [r for r in public_apis.requests[calls:] if "commoncrawl" in r and "collinfo" not in r]


# ---- Wikidata ----------------------------------------------------------------------------------------------------

def wikidata_api(entities: dict, search_ids: list[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if params["action"] == "wbsearchentities":
            return httpx.Response(200, json={"search": [{"id": i} for i in search_ids]})
        return httpx.Response(200, json={"entities": {i: entities[i] for i in params["ids"].split("|")
                                                      if i in entities}})
    return handler


def claim(value: str, **qualifiers) -> dict:
    snak = {"mainsnak": {"datavalue": {"type": "wikibase-entityid", "value": {"id": value}}}}
    if qualifiers:
        snak["qualifiers"] = {k: [{"datavalue": {"value": v}}] for k, v in qualifiers.items()}
    return snak


def human(name: str) -> dict:
    return {"labels": {"en": {"value": name}}, "claims": {"P31": [claim("Q5")]}}


def test_wikidata_people_of_the_company_entity_only(client_for, db, public_apis):
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = new_company(agent, "Omega Bank", industry="Financial Services",
                             website="https://www.omegabank.example")
    entities = {
        "Q1": {"labels": {"en": {"value": "Omega Bank"}}, "claims": {
            "P856": [{"mainsnak": {"datavalue": {"value": "https://www.omegabank.example"}}}],
            "P17": [claim("Q822")],
            "P169": [claim("Q10")], "P488": [claim("Q11", P582="+2019-01-01T00:00:00Z")],
            "P112": [claim("Q13")], "P749": [claim("Q2")]}},
        "Q2": {"labels": {"en": {"value": "Omega Group"}}, "claims": {"P169": [claim("Q12")]}},
        "Q3": {"labels": {"en": {"value": "Omega Bank"}}, "claims": {"P17": [claim("Q142")], "P169": [claim("Q14")]}},
        "Q10": human("Rami Haddad"), "Q11": human("Nabil Saad"), "Q12": human("Group Boss"),
        "Q13": {"labels": {"en": {"value": "Omega Holding"}}, "claims": {"P31": [claim("Q4830453")]}},
        "Q14": human("French Namesake")}
    public_apis.routes[("www.wikidata.org", "/w/api.php")] = wikidata_api(entities, ["Q3", "Q2", "Q1"])
    external.run(db, company_id, force=True)
    people = people_of(db, company_id)
    assert set(people) == {"Rami Haddad | Chief Executive Officer", "Nabil Saad | Chairperson"}
    assert people["Rami Haddad | Chief Executive Officer"].employment_status == "unknown"  # undated open data
    assert people["Nabil Saad | Chairperson"].employment_status == "former"  # an end date
    # never the parent group's CEO, a French namesake's, nor an organisation as "founder"


# ---- asynchronous, reproducible -------------------------------------------------------------------------------------


def test_people_research_stays_asynchronous(client_for, db, public_apis):
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = new_company(agent, "Omega Bank", industry="Financial Services",
                             website="https://www.omegabank.example")
    response = agent.get(f"/companies/{company_id}")
    assert response.status_code == 200
    assert not public_apis.requests  # opening a company never waits for any external source


def test_coverage_benchmark_is_reproducible(client_for, db):
    from scripts.people_coverage import measure

    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = new_company(agent, "Omega Bank", industry="Financial Services")
    pages, _ = documents.pdf_pages(ALMANAC)
    keep(db, "abl_almanac", "https://abl.example/almanac.pdf", parsers.abl_almanac(pages), raw=ALMANAC,
         doc_type="pdf", published=NOW)
    pack.apply(db, db.get(Company, company_id))
    first, second = measure([company_id]), measure([company_id])
    assert first == second
    assert first["by_source"]["abl_almanac"]["unique_people"] == first["people_total"] >= 5
    assert first["by_source"]["abl_almanac"]["companies_not_covered_by_website"] == 1
    assert first["with_current_decision_maker"] == 1


def test_a_global_brand_domain_never_brings_its_executives(client_for, db, public_apis):
    """A Lebanese store / franchise whose website is the global brand's: the brand's Wikidata item (located abroad)
    and its archived pages are not this company's; nothing is attached."""
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = new_company(agent, "Omega Sports", industry="Retail", website="https://www.omegasports.example")
    entities = {"Q1": {"labels": {"en": {"value": "Omega Sports Inc."}}, "claims": {
        "P856": [{"mainsnak": {"datavalue": {"value": "https://www.omegasports.example"}}}],
        "P17": [claim("Q30")], "P169": [claim("Q10")], "P112": [claim("Q11")]}},
        "Q10": human("Global Chief"), "Q11": human("Brand Founder")}
    public_apis.routes[("www.wikidata.org", "/w/api.php")] = wikidata_api(entities, ["Q1"])
    result = external.run(db, company_id, force=True)
    assert people_of(db, company_id) == {}
    assert result["foreign_brand_domain"] == 1 and result["common_crawl_skipped_foreign_brand"] == 1
    assert not [r for r in public_apis.requests if "commoncrawl" in r]


def test_a_lebanese_item_located_by_its_headquarters_city_is_not_a_foreign_brand(client_for, db, public_apis):
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = new_company(agent, "Cedar Bank", industry="Financial Services", website="https://www.cedarbank.example")
    entities = {"Q1": {"labels": {"en": {"value": "Cedar Bank S.A.L."}}, "claims": {
        "P856": [{"mainsnak": {"datavalue": {"value": "https://www.cedarbank.example"}}}],
        "P159": [claim("Q3820")], "P169": [claim("Q10")]}},  # headquarters: Beirut (no country claim)
        "Q3820": {"claims": {"P17": [claim("Q822")]}}, "Q10": human("Rami Haddad")}
    public_apis.routes[("www.wikidata.org", "/w/api.php")] = wikidata_api(entities, ["Q1"])
    result = external.run(db, company_id, force=True)
    assert "foreign_brand_domain" not in result
    assert set(people_of(db, company_id)) == {"Rami Haddad | Chief Executive Officer"}
