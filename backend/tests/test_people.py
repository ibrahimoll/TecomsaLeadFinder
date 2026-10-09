"""People discovery (Step 5): candidates from the company's stored website pages, title / department / seniority
taxonomy, entity resolution, current vs former roles, public contacts (never guessed), evidence, ranking,
human corrections, re-use of stored pages, idempotency and freshness. Websites are mocked."""

import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.models import (AuditLog, Company, CompanyPerson, CompanyWebPage, Email, Evidence, Person, Phone,
                        PossibleDuplicatePerson, ResearchRun)
from app.models.enums import UserRole
from app.services import jobs
from app.services.people import extract as people_extract
from app.services.people import orchestrator as people
from app.services.people.candidate import PersonCandidate
from app.services.people.persistence import save
from app.services.people.resolution import resolve
from app.services.people.titles import classify
from tests.test_enrichment import count, new_company, research, site  # noqa: F401 - the mocked-web fixture

HOME = """<html><head><title>ABC Foods | Home</title></head><body><nav><a href="/about-us">About us</a>
<a href="/team">Our team</a><a href="/news">News</a><a href="/contact">Contact</a><a href="/careers">Careers</a></nav>
<p>ABC Foods manufactures biscuits in Zahle.</p></body></html>"""
TEAM = """<html><title>Our team</title><body><h1>Our Leadership</h1>
<h3>John Haddad</h3><p>Chief Executive Officer</p>
<p>John has led ABC Foods since 2010 and oversees the group's factories across Lebanon.</p>
<h3>Rami Saad</h3><p>IT Manager</p><p>Email: rami.saad@abcfoods.example | Tel: 01 234 567</p>
<p>Sarah Khoury - Marketing Director</p>
<p>CFO: Nadim Abi Nader</p>
<p>جوزيف حداد، المدير العام</p>
<h2>Testimonials</h2><p>“ABC Foods are the best supplier we ever had, always on time.”</p>
<p>Tony Rizk, Purchasing Manager</p></body></html>"""
ABOUT = """<html><title>About ABC Foods</title><body><h1>About us</h1>
<p>ABC Foods was founded by Elie Haddad in 1965 and is now a leading biscuit maker.</p>
<p>Our IT department is headed by Rami Saad, who also runs our ERP project.</p>
<p>Sarah Haddad, our former Marketing Director, retired in 2021.</p>
<p>Georges Daher served as Chief Financial Officer from 2015 to 2020.</p>
<p>Fadi Kassab, CEO of Rival Industries, visited our plant last year.</p></body></html>"""
NEWS = """<html><title>News</title><body><h3>ABC Foods appoints a new HR Manager</h3>
<p>We are pleased to announce Maya Saad as our new HR Manager.</p>
<p>By Lara Saleh, Communications</p></body></html>"""
CONTACT = """<html><title>Contact us</title><body><p>Sales Manager: Nour Hamdan</p>
<p>Email: sales@abcfoods.example</p><p>info@abcfoods.example</p></body></html>"""
CAREERS = """<html><title>Careers</title><body><h3>Accountant</h3>
<p>For inquiries contact Rita Haddad, HR Officer.</p></body></html>"""
ABC = {"/": HOME, "/team": TEAM, "/about-us": ABOUT, "/news": NEWS, "/contact": CONTACT, "/careers": CAREERS}


def abc(client, site, pages=ABC) -> int:  # noqa: F811
    site.sites["www.abcfoods.example"] = dict(pages)
    return new_company(client, name="ABC Foods", website="https://www.abcfoods.example")


def roles(db, company_id: int) -> dict[str, CompanyPerson]:
    db.expire_all()
    rows = db.execute(select(Person.full_name, CompanyPerson).join(CompanyPerson)
                      .where(CompanyPerson.company_id == company_id)).all()
    return {f"{name} | {role.job_title}": role for name, role in rows}


# ---- the people of one company website ---------------------------------------------------------------------------


def test_people_from_the_company_website(client_for, db, site):  # noqa: F811
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = abc(agent, site)
    detail = research(agent, company_id)
    assert (detail["company"]["people_status"], detail["company"]["enrichment_status"]) == ("completed", "completed")
    found = roles(db, company_id)
    assert set(found) == {
        "John Haddad | Chief Executive Officer", "Rami Saad | IT Manager", "Rami Saad | Head of IT",
        "Sarah Khoury | Marketing Director", "Nadim Abi Nader | CFO", "جوزيف حداد | المدير العام",
        "Elie Haddad | Founder", "Sarah Haddad | Marketing Director", "Georges Daher | Chief Financial Officer",
        "Maya Saad | HR Manager", "Nour Hamdan | Sales Manager", "Rita Haddad | HR Officer"}
    # Never: a testimonial's author, another company's CEO, an article's author.
    names = {p.full_name for p in db.scalars(select(Person))}
    assert not names & {"Tony Rizk", "Fadi Kassab", "Lara Saleh"}
    ceo = found["John Haddad | Chief Executive Officer"]
    assert (ceo.normalized_title, ceo.department, ceo.seniority, ceo.employment_status, ceo.title_rank) == (
        "CEO", "executive", "c_level", "current", 1)
    assert (found["جوزيف حداد | المدير العام"].normalized_title, found["جوزيف حداد | المدير العام"].department) == (
        "General Manager", "executive")
    # Current vs former vs not established.
    assert found["Georges Daher | Chief Financial Officer"].employment_status == "former"
    assert found["Georges Daher | Chief Financial Officer"].ended_at.year == 2020
    assert found["Sarah Haddad | Marketing Director"].employment_status == "former"
    assert found["Elie Haddad | Founder"].employment_status == "unknown"  # founded in 1965: history
    # One person, two stated titles from two pages: one identity, both titles kept, both sources.
    rami = db.scalar(select(Person).where(Person.full_name == "Rami Saad"))
    assert {r.normalized_title for r in db.scalars(select(CompanyPerson).where(CompanyPerson.person_id == rami.id))} \
        == {"IT Manager", "Head of IT"}
    # Public contacts only where published with the person; a generic mailbox is never a person's.
    assert [(e.email, e.status) for e in db.scalars(select(Email).where(Email.person_id.is_not(None)))] == [
        ("rami.saad@abcfoods.example", "published")]
    assert [p.normalized_phone for p in db.scalars(select(Phone).where(Phone.person_id.is_not(None)))] == [
        "+9611234567"]
    assert count(db, Email, Email.status == "predicted") == 0
    # Evidence for every role, with its source page and excerpt.
    assert count(db, CompanyPerson, CompanyPerson.company_id == company_id) == count(
        db, Evidence, Evidence.evidence_type == "employment", Evidence.company_person_id.is_not(None))
    cfo = db.scalar(select(Evidence).join(CompanyPerson).where(CompanyPerson.job_title == "CFO"))
    assert cfo.excerpt == "CFO: Nadim Abi Nader" and cfo.structured_value["source_type"] == "team"
    # The API: key decision-maker per department, current over former, sources listed.
    people_out = agent.get(f"/companies/{company_id}/people").json()
    key = {p["department"]: p["person"]["full_name"] + " | " + p["job_title"] for p in people_out if p["is_key"]}
    assert key == {"executive": "John Haddad | Chief Executive Officer", "it": "Rami Saad | Head of IT",
                   "marketing": "Sarah Khoury | Marketing Director", "finance": "Nadim Abi Nader | CFO",
                   "hr": "Maya Saad | HR Manager", "sales": "Nour Hamdan | Sales Manager"}
    head_of_it = next(p for p in people_out if p["job_title"] == "Head of IT")
    assert head_of_it["sources"][0]["url"].endswith("/about-us")
    company = db.get(Company, company_id)
    assert company.people_coverage["found"] == 6 and company.people_coverage["procurement"] is False
    assert company.status == "new"  # people discovery never touches the sales status


def test_people_need_a_website_confirmed_as_the_companys(client_for, db, site):  # noqa: F811
    agent, _ = client_for(UserRole.SALES_AGENT)
    site.sites["www.abcfoods.example"] = {**ABC, "/": "<html><title>Some shop</title><p>Shoes.</p></html>"}
    company_id = new_company(agent, name="Unrelated Mills", website="https://www.abcfoods.example")
    c = research(agent, company_id)["company"]
    assert c["people_status"] == "partial" and count(db, Person) == 0


def test_a_brand_sites_people_are_not_this_companys(client_for, db, site):  # noqa: F811
    agent, _ = client_for(UserRole.SALES_AGENT)
    site.sites["www.abcfoods.example"] = dict(ABC)
    company_id = new_company(agent, name="ABC Foods Zahle", website="https://www.abcfoods.example/zahle")
    c = research(agent, company_id)["company"]
    assert c["people_status"] == "partial" and "larger brand" in c["people_message"] and count(db, Person) == 0
    assert people.brand_page("https://abc.example/") is False and people.brand_page("https://abc.example/en-gb/") \
        is False and people.brand_page("https://www.nike.com/lb/retail/s/nike-abc") is True


def test_shop_and_home_page_text_is_not_people():
    from app.services.enrichment.extract import Context
    from app.services.enrichment.pages import parse

    html = """<h3>Foundation Finder</h3><p>Skincare Pro Advisor</p>
    <p>Visit the eco-friendly farm tended by Chief Gardener - Mohamed Ramadan</p>
    <p>Head of IT &amp; PMO, ABC Mall, Lebanon</p><p>IT Director, BDO ESNAD, Egypt</p>
    <p>Group Head of Technology, Newroz Telecom – Iraq</p>
    <h3>Role Description</h3><p>Senior Sales Manager</p>"""  # client testimonial credits, a job posting
    ctx = Context("Kiko", "LB", "Lebanon", "kiko.example")
    for page_type in ("homepage", "about"):
        assert not people_extract.extract(parse(html, "https://kiko.example/"), page_type, ctx=ctx, source_id=1,
                                          url=None, observed_at=datetime.now(timezone.utc), ownership=100)


def test_no_public_people_is_reported_not_invented(client_for, db, site):  # noqa: F811
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = abc(agent, site, {"/": HOME})
    c = research(agent, company_id)["company"]
    assert (c["people_status"], c["people_message"], count(db, Person)) == ("completed", None, 0)
    offline = new_company(agent, name="Offline Bakery", website=None)
    agent.get(f"/companies/{offline}/people")
    while jobs.run_next(jobs.RESEARCH):
        pass
    c = agent.get(f"/companies/{offline}").json()["company"]
    assert c["people_status"] == "completed" and "No company website" in c["people_message"]


# ---- stored pages, idempotency, freshness ----------------------------------------------------------------------


def test_stored_pages_are_reused_and_research_is_idempotent(client_for, db, site):  # noqa: F811
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = abc(agent, site)
    research(agent, company_id)
    before = (count(db, Person), count(db, CompanyPerson), count(db, Evidence), count(db, Email), count(db, Phone))
    requests = len(site.requests)
    run = people.run(db, company_id, force=False)  # again, from the stored pages
    assert len(site.requests) == requests  # nothing fetched
    assert run["pages_unchanged"] == 6 and run.get("pages_read", 0) == 0
    assert (count(db, Person), count(db, CompanyPerson), count(db, Evidence), count(db, Email),
            count(db, Phone)) == before
    forced = people.run(db, company_id, force=True)  # everything read again: still nothing new
    assert forced["pages_read"] == 6 and forced["merged"] == forced["candidates"]
    assert (count(db, Person), count(db, CompanyPerson), count(db, Evidence)) == before[:3]


def test_a_changed_team_page_is_read_again(client_for, db, site):  # noqa: F811
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = abc(agent, site)
    research(agent, company_id)
    site.sites["www.abcfoods.example"]["/team"] = TEAM.replace("<h3>John Haddad</h3><p>Chief Executive Officer</p>",
                                                               "<h3>Karim Nassar</h3><p>Chief Executive Officer</p>")
    team = db.scalar(select(CompanyWebPage).where(CompanyWebPage.company_id == company_id,
                                                  CompanyWebPage.page_type == "team"))
    team.retrieved_at = datetime.now(timezone.utc) - timedelta(days=people.PAGE_STALE_DAYS + 1)  # stale
    db.commit()
    run = people.run(db, company_id)
    assert run["pages_read"] == 1 and run["pages_fetched"] == 1  # only the stale team page is fetched again
    found = roles(db, company_id)
    assert found["Karim Nassar | Chief Executive Officer"].employment_status == "current"
    # No longer on the page: not current any more, but kept (never deleted).
    assert found["John Haddad | Chief Executive Officer"].employment_status == "unknown"


def test_fresh_people_research_is_not_repeated(client_for, db, site):  # noqa: F811
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = abc(agent, site)
    research(agent, company_id)
    for _ in range(2):
        agent.get(f"/companies/{company_id}/people")
        agent.get(f"/companies/{company_id}")
    assert count(db, ResearchRun, ResearchRun.research_type == "people_discovery") == 1
    agent.post(f"/companies/{company_id}/refresh")  # Refresh Research: company, then its people
    while jobs.run_next(jobs.RESEARCH):
        pass
    assert count(db, ResearchRun, ResearchRun.research_type == "people_discovery") == 2


# ---- resolution ----------------------------------------------------------------------------------------------------


def candidate(company_id: int, source_id: int, name: str, title: str, **kw) -> PersonCandidate:
    t = classify(title)
    return PersonCandidate(source_id=source_id, source_url="https://x.example/team", source_type="team",
                           company_id=company_id, full_name=name, raw_title=title, evidence_excerpt=f"{name} {title}",
                           normalized_title=t.normalized, department=t.department, seniority=t.seniority,
                           title_rank=t.rank, title_explicit=t.explicit, source_confidence=95,
                           company_match_confidence=95, **kw)


@pytest.fixture
def two_companies(db):
    from app.models import Source

    a, b = Company(name="Alpha Foods", normalized_name="alpha foods"), Company(name="Beta Foods",
                                                                                normalized_name="beta foods")
    source = Source(source_type="company_website", name="team page", url="https://x.example/team")
    db.add_all([a, b, source])
    db.commit()
    return a, b, source


def stored(db, company: Company, c: PersonCandidate) -> CompanyPerson:
    role = save(db, company, c, resolve(db, company.id, c), datetime.now(timezone.utc))
    db.commit()
    return role


def test_entity_resolution(db, two_companies):
    a, b, source = two_companies
    joe = stored(db, a, candidate(a.id, source.id, "Joe Haddad", "IT Manager"))
    joseph = stored(db, a, candidate(a.id, source.id, "Joseph Haddad", "Head of IT"))
    initial = stored(db, a, candidate(a.id, source.id, "J. Haddad", "Head of IT"))
    assert joe.person_id == joseph.person_id == initial.person_id  # same company + matching role evidence
    john = stored(db, a, candidate(a.id, source.id, "John Haddad", "Sales Manager"))
    johnny = stored(db, a, candidate(a.id, source.id, "Johnny Haddad", "Sales Manager"))
    assert john.person_id != johnny.person_id  # fuzzy names are never merged...
    assert db.scalar(select(func.count()).select_from(PossibleDuplicatePerson)) == 1  # ...only flagged
    smith_a = stored(db, a, candidate(a.id, source.id, "John Smith", "CEO"))
    smith_b = stored(db, b, candidate(b.id, source.id, "John Smith", "CEO"))
    assert smith_a.person_id != smith_b.person_id  # the same name at two companies: two people
    other_role = stored(db, a, candidate(a.id, source.id, "John Smith", "Chief Financial Officer"))
    assert other_role.person_id != smith_a.person_id  # same name, conflicting role: kept apart (flagged)
    shared = stored(db, b, candidate(b.id, source.id, "Rami Saad", "IT Manager", email="rami@alpha.example"))
    moved = stored(db, a, candidate(a.id, source.id, "Rami Saad", "IT Director", email="rami@alpha.example"))
    assert shared.person_id == moved.person_id  # the same published email: one person, two employers


def test_current_role_is_preferred_and_conflicting_titles_are_kept(client_for, db, site):  # noqa: F811
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = abc(agent, site)
    research(agent, company_id)
    marketing = [p for p in agent.get(f"/companies/{company_id}/people").json() if p["department"] == "marketing"]
    assert {(p["person"]["full_name"], p["employment_status"], p["is_key"]) for p in marketing} == {
        ("Sarah Khoury", "current", True), ("Sarah Haddad", "former", False)}


def test_a_human_correction_is_never_overwritten(client_for, db, site):  # noqa: F811
    agent, user = client_for(UserRole.SALES_AGENT)
    company_id = abc(agent, site)
    research(agent, company_id)
    role = roles(db, company_id)["Nour Hamdan | Sales Manager"]
    response = agent.patch(f"/companies/{company_id}/people/{role.id}",
                           json={"job_title": "Head of Sales", "department": "sales", "employment_status": "former"})
    assert response.status_code == 200 and response.json()["corrected_fields"] == [
        "department", "employment_status", "job_title"]
    agent.post(f"/companies/{company_id}/refresh")
    while jobs.run_next(jobs.RESEARCH):
        pass
    db.refresh(role)
    assert (role.job_title, role.employment_status, role.is_current) == ("Head of Sales", "former", False)
    assert db.scalar(select(AuditLog).where(AuditLog.action == "company.person_corrected")) is not None
    assert agent.patch(f"/companies/{company_id}/people/{role.id}", json={"department": "astrology"}
                       ).status_code == 422


# ---- taxonomy ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("raw, normalized, department, seniority", [
    ("Chief Executive Officer", "CEO", "executive", "c_level"),
    ("Founder & CEO", "CEO", "executive", "c_level"),
    ("Managing Director", "Managing Director", "executive", "c_level"),
    ("Directeur Général", "General Manager", "executive", "c_level"),
    ("Directeur Financier", "Finance Director", "finance", "director"),
    ("Responsable Informatique", "IT Manager", "it", "manager"),
    ("مدير عام", "General Manager", "executive", "c_level"),
    ("مدير تكنولوجيا المعلومات", "IT Manager", "it", "manager"),
    ("Head of IT", "Head of IT", "it", "head"),
    ("Information Technology Manager", "IT Manager", "it", "manager"),
    ("Senior Accountant", "Accountant", "finance", "senior"),
    ("Digital Marketing Manager", "Digital Marketing Manager", "marketing", "manager"),
    ("Procurement Manager", "Procurement Manager", "procurement", "manager"),
    ("Logistics Manager", "Logistics Manager", "supply_chain", "manager"),
    ("Factory Manager", "Factory Manager", "manufacturing", "manager"),
    ("Assistant Marketing Manager", None, "marketing", "senior"),  # not THE marketing manager
    ("Executive Chef", None, "other", "individual_contributor"),  # unknown: raw title kept, nothing guessed
    ("Chief Distribution Officer (CDO)", None, "executive", "c_level"),  # not the Chief Digital Officer
    ("CEO (Chief Executive Officer)", "CEO", "executive", "c_level"),
])
def test_title_taxonomy(raw, normalized, department, seniority):
    t = classify(raw)
    assert (t.raw, t.normalized, t.department, t.seniority) == (raw, normalized, department, seniority)


def test_decision_maker_ranking():
    it = [classify(t) for t in ("Systems Manager", "IT Manager", "CIO", "Head of IT", "CTO", "IT Director",
                                 "ERP Manager", "Infrastructure Manager")]
    assert [t.normalized for t in sorted(it, key=lambda t: t.rank)] == [
        "CIO", "CTO", "IT Director", "Head of IT", "IT Manager", "Infrastructure Manager", "ERP Manager",
        "Systems Manager"]
    assert classify("Welcome to our website") is None and classify("Board Member").normalized == "Board Member"
    assert classify("Senior") is None and classify("Sales Manager (North").normalized == "Sales Manager"
    assert classify("Assistant").seniority == "individual_contributor"


# ---- the job never blocks the API --------------------------------------------------------------------------------


def test_people_discovery_does_not_block_the_api(client_for, db, site, monkeypatch):  # noqa: F811
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = abc(agent, site)
    agent.get(f"/companies/{company_id}")
    assert jobs.run_next((jobs.ENRICHMENT,))  # company research; people discovery is now queued
    original = people_extract.extract

    def slow(*args, **kwargs):
        time.sleep(0.3)
        return original(*args, **kwargs)
    monkeypatch.setattr(people, "extract", slow)
    worker = threading.Thread(target=lambda: jobs.run_next((jobs.PEOPLE,)))
    worker.start()
    time.sleep(0.4)
    started = time.monotonic()
    status = agent.get(f"/companies/{company_id}").json()["company"]["people_status"]
    assert agent.get("/companies").status_code == 200 and time.monotonic() - started < 1.0
    assert status == "researching"
    worker.join(30)
    assert agent.get(f"/companies/{company_id}").json()["company"]["people_status"] == "completed"


def test_extraction_context():
    from app.services.enrichment.extract import Context
    from app.services.enrichment.pages import parse

    html = """<p>Lina Farah - Head of Marketing</p><p>Karim Aoun, Director of Human Resources at ABC Foods.</p>
    <p>Fadi Kassab, CEO of Rival Industries, visited our plant.</p><p>Maher Daou is the CFO of Delta Bank.</p>
    <p>Rita Saba, our former Sales Director, retired in 2022.</p>
    <p>The lab was opened by our CEO Andre Fadel and MediLife General Manager Nicole Bassim.</p>
    <p>The board welcomed its Chairman, and CEO Rizk El Khoury.</p>
    <p>Our CEO, Ziad Nassar, and MediLife General Manager, Nicole Bassim, represented our team.</p>
    <p>The company built its reputation as a key supplier and partner to Original Equipment Manufacturers.</p>
    <p>The estate was planted by Boutros Haddad, father of the founder, in 1930.</p>
    <p>In 2014, Ronald Saliba was appointed Chairman of the company.</p>"""
    found = {(c.full_name, c.normalized_title, c.status, c.raw_title) for c in people_extract.extract(
        parse(html, "https://abcfoods.example/about"), "about", ctx=Context("ABC Foods", "LB", "Lebanon",
                                                                             "abcfoods.example"),
        source_id=1, url=None, observed_at=datetime.now(timezone.utc), ownership=90)}
    assert {f[:3] for f in found} == {
        ("Lina Farah", "Head of Marketing", "current"), ("Karim Aoun", "HR Director", "current"),
        ("Rita Saba", "Sales Director", "former"), ("Andre Fadel", "CEO", "current"),
        ("Rizk El Khoury", "CEO", "current"), ("Ziad Nassar", "CEO", "current"),
        ("Nicole Bassim", "General Manager", "current"), ("Ronald Saliba", "Chairman", "current")}
    assert {f[3] for f in found if f[0] == "Nicole Bassim"} == {"MediLife General Manager"}
    assert {f[3] for f in found if f[0] == "Ronald Saliba"} == {"Chairman"}


def test_team_page_layout_is_read_once_for_the_whole_page():
    """Menus whose items look like names, then title-above-name cards. Each name gets its own title, never its
    neighbour's."""
    from app.services.enrichment.extract import Context
    from app.services.enrichment.pages import parse

    html = """<ul><li>Current Account Fresh</li><li>Fresh Time Deposit</li></ul>
    <h4>General Manager - Chief Executive Officer</h4><h3>Hani DANNAWI</h3>
    <h4>DGM - Chief Financial Officer</h4><h3>Naji ECHO</h3>
    <h4>AGM – Head of Treasury, Financial Markets &amp; Assets Management Division</h4><h3>Carlos LEBBOS</h3>
    <h4>Head of Branches Network Division</h4>
    <p>Corporate Banking - Commercial</p><p>Private Banking: Wealth Management</p>"""
    found = {(c.full_name, c.raw_title, c.normalized_title) for c in people_extract.extract(
        parse(html, "https://bank.example/management"), "team", ctx=Context("Bank", "LB", "Lebanon", "bank.example"),
        source_id=1, url=None, observed_at=datetime.now(timezone.utc), ownership=100)}
    assert found == {("Hani Dannawi", "General Manager - Chief Executive Officer", "CEO"),
                     ("Naji Echo", "DGM - Chief Financial Officer", "CFO"),
                     ("Carlos Lebbos", "AGM – Head of Treasury, Financial Markets & Assets Management Division", None)}
    # the real BLC page: name (h3) above title (h4), its first name unrecognised ("H.E. Mr."): no shift by one card
    real = """<h3>H.E. Mr. Mansour BTEISH</h3><h4>General Manager - Chief Executive Officer</h4>
    <h3>Hani DANNAWI</h3><h4>DGM - Chief Financial Officer</h4><h3>Naji ECHO</h3><h4>Chief Audit Officer</h4>"""
    found = {(c.full_name, c.raw_title) for c in people_extract.extract(
        parse(real, "https://bank.example/management"), "team", ctx=Context("Bank", "LB", "Lebanon", "bank.example"),
        source_id=1, url=None, observed_at=datetime.now(timezone.utc), ownership=100)}
    assert ("Hani Dannawi", "DGM - Chief Financial Officer") in found and ("Naji Echo", "Chief Audit Officer") in found
    assert not any(t.startswith("General Manager") for n, t in found if n != "Mansour Bteish")
