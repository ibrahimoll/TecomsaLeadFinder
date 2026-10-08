"""Company intelligence from free public sources: hospital directory, GLEIF (legal identity, parents), public
procurement awards (signals, never people), business news (dated events = the timeline), passive DNS / RDAP
technology, directory company facts (evidence-first, never overwriting typed values), the local source index
(full-text search) and field completeness. Every page and API is mocked."""

import json
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from app.models import (Company, CompanyIdentifier, CompanyLocation, CompanyPerson, CompanyRelationship,
                        CompanySignal, Email, Evidence, ExternalDocument, Phone)
from app.models.enums import UserRole
from app.services import completeness
from app.services.enrichment import domain_intel
from app.services.enrichment.pages import parse
from app.services.people.external import corpus, orchestrator as external
from app.services.people.external.lebanon import news, pack, parsers
from app.services.people.external.lebanon.records import Record

from .test_external_people import count, roles, web  # noqa: F401  (fixture)
from .test_lebanon_sources import keep, new_company

NOW = datetime.now(timezone.utc)
HOSPITAL = """<html><body><nav><li>Home</li></nav><table><tr><th colspan="2">Cedar Hospital </th></tr>
<tr><td>Date of Establishment</td><td>1/1/1968 </td></tr><tr><td>Chair Person</td><td>Cedar University</td></tr>
<tr><td>CEO</td><td>Dr. Rami Haddad</td></tr><tr><td>Location</td><td>Beirut</td></tr>
<tr><td>Address</td><td>Hamra Street - Beirut - Lebanon</td></tr><tr><td>Phone Number(s)</td><td>01-350000 / 350001</td></tr>
<tr><td>E-mail</td><td>info@cedarhospital.example</td></tr><tr><td>Web Site</td><td>www.cedarhospital.example</td></tr>
<tr><td>Number of Beds</td><td>250</td></tr></table></body></html>"""


def test_hospital_directory_people_and_company_facts(client_for, db):
    records = parsers.hospital(parse(HOSPITAL, "https://hospitals.example/Hospitals/Details/7"))
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = new_company(agent, "Cedar Hospital", industry="Healthcare", website="https://www.cedarhospital.example")
    keep(db, "hospital_syndicate", "https://hospitals.example/Hospitals/Details/7", records)
    pack.apply(db, db.get(Company, company_id))
    people = roles(db, company_id)
    assert set(people) == {"Rami Haddad | CEO"}  # "Cedar University" as chair is an organisation, not a person
    assert people["Rami Haddad | CEO"].employment_status == "unknown"  # an undated directory page
    company = db.get(Company, company_id)
    assert company.founded_year == 1968 and company.primary_email == "info@cedarhospital.example"
    assert company.primary_phone  # the published number, normalised
    assert db.scalar(select(CompanySignal.signal_value).where(CompanySignal.company_id == company_id,
                                                              CompanySignal.signal_type == "hospital_beds")) == "250"
    hq = db.scalar(select(CompanyLocation).where(CompanyLocation.company_id == company_id,
                                                 CompanyLocation.address.like("Hamra%")))
    assert hq.location_type == "headquarters"


def test_directory_facts_are_evidence_and_never_overwrite_typed_values(client_for, db):
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = new_company(agent, "Omega Bank", industry="Financial Services")
    company = db.get(Company, company_id)
    company.employee_count_estimate = 999  # typed in by a person
    db.commit()
    bank = Record(org=["OMEGA BANK S.A.L."], excerpt="OMEGA BANK S.A.L.",
                  facts={"employees": 75, "branches": 3, "phone": "(01) 748061", "email": "info@omegabank.example"})
    keep(db, "abl_almanac", "https://abl.example/almanac.pdf", [bank], published=NOW - timedelta(days=100),
         doc_type="pdf")
    pack.apply(db, db.get(Company, company_id))
    pack.apply(db, db.get(Company, company_id))  # idempotent
    db.expire_all()
    company = db.get(Company, company_id)
    assert company.employee_count_estimate == 999  # kept: a person's value is never silently replaced
    employees = db.scalars(select(Evidence).where(Evidence.company_id == company_id,
                                                  Evidence.field_name == "employee_count_estimate")).all()
    assert [e.extracted_value for e in employees] == ["75"]  # the source's value kept as evidence, once
    assert employees[0].structured_value["kind"] == "exact" and employees[0].structured_value["as_of"]
    assert count(db, Phone, Phone.company_id == company_id, Phone.person_id.is_(None)) == 1
    assert count(db, Email, Email.company_id == company_id) == 1
    assert db.scalar(select(CompanySignal.signal_value).where(CompanySignal.company_id == company_id,
                                                              CompanySignal.signal_type == "branches")) == "3"
    # nothing invented: a directory without a count gives no size
    other = new_company(agent, "Cedar Bank", industry="Financial Services")
    keep(db, "abl_hr", "https://abl.example/hr", [Record(org=["Cedar Bank"], excerpt="Cedar Bank")])
    pack.apply(db, db.get(Company, other))
    assert count(db, Evidence, Evidence.company_id == other, Evidence.field_name.like("employee%")) == 0


def test_ministry_factory_location_and_activity(client_for, db):
    from .test_lebanon_sources import row

    records = parsers.ministry_rows([row("201.0", "شركة اوميغا فودز ش.م.م", website="www.omegafoods.example")], 2022)
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = new_company(agent, "Omega Foods", industry="Food Manufacturing", website="https://www.omegafoods.example")
    keep(db, "ministry_industry", "https://industry.example/food.xls", records, doc_type="xls",
         published=datetime(2022, 12, 31, tzinfo=timezone.utc))
    pack.apply(db, db.get(Company, company_id))
    site = db.scalar(select(CompanyLocation).where(CompanyLocation.company_id == company_id,
                                                   CompanyLocation.location_type == "factory"))
    assert site is not None and site.is_headquarters is False  # a factory, not the head office
    types = set(db.scalars(select(CompanySignal.signal_type).where(CompanySignal.company_id == company_id)))
    assert {"manufacturing", "factory"} <= types


GLEIF_ENTRIES = [
    {"id": "LEI0000000000000OMEG", "attributes": {"lei": "LEI0000000000000OMEG", "entity": {
        "status": "ACTIVE", "legalName": {"name": "OMEGA FOODS S.A.L."}, "registeredAs": "1012345",
        "legalForm": {"other": "Societe Anonyme Libanaise"},
        "legalAddress": {"addressLines": ["Main road", "Zalka"], "city": "Zalka", "country": "LB"}},
        "registration": {"lastUpdateDate": "2026-05-01T00:00:00Z"}},
     "parents": [{"type": "parent", "lei": "LEI0000000000000HOLD", "name": "OMEGA HOLDING S.A.L."},
                 {"type": "ultimate_parent", "lei": "LEI0000000000000GLOB", "name": "OMEGA GLOBAL PLC"}]},
    {"id": "LEI0000000000000HOLD", "attributes": {"lei": "LEI0000000000000HOLD", "entity": {
        "status": "ACTIVE", "legalName": {"name": "OMEGA HOLDING S.A.L."}, "legalAddress": {"city": "Beirut"}}},
     "parents": []},
]


def test_gleif_legal_identity_and_parent_relationships(client_for, db):
    agent, _ = client_for(UserRole.SALES_AGENT)
    foods = new_company(agent, "Omega Foods", industry="Food Manufacturing")
    holding = new_company(agent, "Omega Holding", industry="Financial Services")
    records = parsers.gleif(GLEIF_ENTRIES)
    keep(db, "gleif", "https://gleif.example/LB", records, doc_type="json")
    for company_id in (holding, foods):  # the holding first: its LEI is known when the subsidiary is matched
        pack.apply(db, db.get(Company, company_id))
    company = db.get(Company, foods)
    assert company.legal_name == "OMEGA FOODS S.A.L."
    ids = dict(db.execute(select(CompanyIdentifier.scheme, CompanyIdentifier.value)
                          .where(CompanyIdentifier.company_id == foods)).all())
    assert ids == {"lei": "LEI0000000000000OMEG", "registry:LB": "1012345"}
    rels = {r.relation_type: r for r in db.scalars(select(CompanyRelationship)
                                                    .where(CompanyRelationship.company_id == foods))}
    assert rels["parent"].related_company_id == holding  # linked, never merged
    assert rels["ultimate_parent"].related_name == "OMEGA GLOBAL PLC" and rels["ultimate_parent"].related_company_id \
        is None
    assert count(db, Company) == 2
    assert roles(db, foods) == {}  # a parent's people are never the subsidiary's (and GLEIF names none)


AWARDS = """<table><tbody>
<tr><td><img alt="Image"/></td><td><a href="https://www.ppa.gov.lb/ar/tenders/details/13010/awards">Supply of IT
equipment / المجموعة (1) - Supply of IT equipment</a></td><td>2026-09-30 10:00:00</td><td>2026-10-14</td>
<td><p>Omega Technology s.a.r.l</p></td><td><p>120,000.00 USD</p></td><td>Details</td></tr>
<tr><td><img alt="Image"/></td><td><a href="https://www.ppa.gov.lb/ar/tenders/details/13011/awards">Road works</a></td>
<td>2026-09-29 10:00:00</td><td>2026-10-13</td><td><p>Delta Contracting</p></td><td><p>1,000.00 USD</p></td>
<td>Details</td></tr></tbody></table>"""


def test_procurement_awards_are_company_signals_never_people(client_for, db):
    records = parsers.ppa_awards(AWARDS)
    assert [r.org for r in records] == [["Omega Technology s.a.r.l"], ["Delta Contracting"]]
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = new_company(agent, "Omega Technology", industry="Technology")
    keep(db, "ppa_awards", "https://www.ppa.gov.lb/ar/awards?page=1", records)
    pack.apply(db, db.get(Company, company_id))
    pack.apply(db, db.get(Company, company_id))
    award = db.scalar(select(CompanySignal).where(CompanySignal.company_id == company_id,
                                                  CompanySignal.signal_type == "procurement_award"))
    assert award.event_date.isoformat() == "2026-09-30" and "Supply of IT equipment" in award.description
    assert award.detail["amount"] == "120,000.00 USD"
    assert count(db, CompanySignal, CompanySignal.signal_type == "procurement_award") == 1  # idempotent, no Delta
    assert roles(db, company_id) == {}


def test_news_events_on_the_timeline_and_people(client_for, db, web):
    article = f"""<html><head><title>Omega Foods opens a new factory in Zahle</title>
    <meta property="article:published_time" content="{(NOW - timedelta(days=60)).date().isoformat()}"></head><body>
    <p>Omega Foods opened a new factory in Zahle on Monday, doubling its capacity, said CEO Michel Haddad.</p>
    <p>Omega Foods CEO Michel Haddad said exports would grow.</p></body></html>"""
    web.sites["news.example"] = {"/business/omega-foods-opens-a-new-factory-in-zahle": article}
    sitemap = ("<urlset><url><loc>https://news.example/business/omega-foods-opens-a-new-factory-in-zahle</loc>"
               "<lastmod>2026-08-01T10:00:00+03:00</lastmod></url><url><loc>https://news.example/life/omega-3"
               "</loc></url><url><loc>https://news.example/business/delta-foods-expands</loc></url></urlset>")
    keep(db, "news_executive", "https://news.example/post-sitemap1.xml", news.sitemap(sitemap), doc_type="xml")
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = new_company(agent, "Omega Foods", industry="Food Manufacturing")
    result = external.run(db, company_id, force=True)
    assert result["news_articles_matched"] == 1  # the slug names the company; 'omega-3' and Delta do not
    event = db.scalar(select(CompanySignal).where(CompanySignal.company_id == company_id,
                                                  CompanySignal.signal_type == "factory_opening"))
    assert event.event_date == (NOW - timedelta(days=60)).date()
    assert event.description.startswith("Omega Foods opens a new factory")
    assert "Michel Haddad | CEO" in roles(db, company_id)
    external.run(db, company_id, force=True)  # idempotent: no duplicate event or person
    assert count(db, CompanySignal, CompanySignal.company_id == company_id,
                 CompanySignal.signal_type == "factory_opening") == 1
    assert len([k for k in roles(db, company_id) if k.startswith("Michel Haddad")]) == 1


def test_news_slugs_are_distinctive():
    assert news.slugs(["Bank Audi", "Bank", "Massabki", "LAU", "The Group"]) == ["bank-audi", "massabki"]
    assert news.classify("ABC Foods appoints Rita Saba as CFO") == "management_change"
    assert news.classify("Omega wins a $2m contract to supply servers") == "procurement_award"
    assert news.classify("Omega opens its second branch in Jounieh") == "branch_opening"
    assert news.classify("Omega's chairman talks about the economy") is None


def test_passive_dns_technology_intelligence(client_for, db, public_apis):
    answers = {("omegatech.example", "MX"): ["10 omegatech-example.mail.protection.outlook.com."],
               ("omegatech.example", "TXT"): ['"v=spf1 include:spf.protection.outlook.com include:servers.mcsv.net -all"'],
               ("_dmarc.omegatech.example", "TXT"): ['"v=DMARC1; p=quarantine; rua=mailto:d@omegatech.example"'],
               ("omegatech.example", "NS"): ["ana.ns.cloudflare.com."]}

    def doh(request: httpx.Request) -> httpx.Response:
        key = (request.url.params["name"], request.url.params["type"])
        return httpx.Response(200, json={"Answer": [{"data": d} for d in answers.get(key, [])]})

    public_apis.routes[("cloudflare-dns.com", "/dns-query")] = doh
    public_apis.routes[("rdap.org", "/domain/omegatech.example")] = lambda r: httpx.Response(
        200, json={"events": [{"eventAction": "registration", "eventDate": "2009-04-02T00:00:00Z"}]})
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = new_company(agent, "Omega Tech", industry="Technology", website="https://www.omegatech.example")
    company = db.get(Company, company_id)
    with pack.api_client() as http:
        assert domain_intel.run(db, company, http) == 5
        assert domain_intel.run(db, company, http) == 0  # fresh: not asked again
    signals = set(db.execute(select(CompanySignal.signal_type, CompanySignal.signal_value)
                             .where(CompanySignal.company_id == company_id)).all())
    assert {("email_provider", "Microsoft 365"), ("email_sending_service", "Microsoft 365"),
            ("email_sending_service", "Mailchimp"), ("email_security", "DMARC p=quarantine"),
            ("dns_provider", "Cloudflare")} <= signals
    registered = db.scalar(select(CompanySignal).where(CompanySignal.signal_type == "domain_registered"))
    assert registered.event_date.isoformat() == "2009-04-02"
    hosts = {r.split("/")[0] for r in public_apis.requests}
    assert hosts <= {"cloudflare-dns.com", "rdap.org"}  # public lookups only: nothing sent to the company itself


def test_local_source_index_full_text_search(client_for, db):
    records = [Record(org=["OMEGA BANK S.A.L."], person="Rana Hage", title="Head of Human Resources",
                      excerpt="OMEGA BANK S.A.L. — Senior Management: Ms. Rana Hage Head of Human Resources"),
               Record(org=["مصرف الأرز"], excerpt="مصرف الأرز ش.م.ل")]
    row = keep(db, "abl_almanac", "https://abl.example/almanac.pdf", records, doc_type="pdf")
    assert row.search_vector is not None or db.scalar(select(ExternalDocument.search_vector).where(
        ExternalDocument.id == row.id)) is not None
    assert [r["url"] for r in corpus.search(db, '"Rana Hage"')] == ["https://abl.example/almanac.pdf"]
    assert corpus.search(db, "Human Resources")[0]["category"] == "association_directory"
    assert corpus.search(db, "مصرف") and not corpus.search(db, "Sales Director")
    again = keep(db, "abl_almanac", "https://abl.example/almanac.pdf", records, doc_type="pdf")
    assert again is None and count(db, ExternalDocument) == 1  # same content hash: one document, not reprocessed


def test_completeness_is_field_coverage(client_for, db):
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = new_company(agent, "Omega Bank", industry="Financial Services")
    company = db.get(Company, company_id)
    empty = completeness.update(db, company)
    assert empty["people"] == 0 and "IT decision-maker" in empty["missing"] and empty["identity"] == 20
    bank = Record(org=["Omega Bank"], excerpt="Omega Bank", identifiers={"bdl_bank_list": "77"},
                  facts={"phone": "(01) 748061", "employees": 75})
    cfo = Record(org=["Omega Bank"], person="Karim Saad", title="Chief Financial Officer",
                 excerpt="Omega Bank — Mr. Karim Saad Chief Financial Officer")
    keep(db, "abl_almanac", "https://abl.example/almanac.pdf", [bank, cfo], published=NOW, doc_type="pdf")
    pack.apply(db, db.get(Company, company_id))
    full = completeness.update(db, db.get(Company, company_id))
    assert full["people"] == round(100 / 8) and "finance decision-maker" not in full["missing"]
    assert full["contacts"] == 50 and full["size"] == 100 and full["identity"] == 40
    assert json.dumps(full)  # stored as plain JSON on the company


def test_audit_fixes_person_mailbox_branch_record_sponsored_article(client_for, db):
    """Audit findings: a contact person's address is not the company e-mail; a branch's own record does not get the
    head office's people / switchboard; a sponsored ('brand voice') article is not reporting."""
    agent, _ = client_for(UserRole.SALES_AGENT)
    benta = new_company(agent, "Benta Pharma", industry="Pharmaceutical")
    branch = new_company(agent, "Omega Bank Dora Branch", industry="Financial Services")
    keep(db, "idal_directories", "https://idal.example/pharma.pdf",
         [Record(org=["Benta Pharma"], excerpt="Benta Pharma", facts={"email": "bernard.tannoury@benta.example"})],
         doc_type="pdf")
    keep(db, "abl_almanac", "https://abl.example/almanac.pdf",
         [Record(org=["Omega Bank Dora Branch"], excerpt="x", facts={"phone": "(01) 748061"}),
          Record(org=["Omega Bank Dora Branch"], person="Karim Saad", title="Chief Financial Officer", excerpt="x")],
         doc_type="pdf", published=NOW)
    pack.apply(db, db.get(Company, benta))
    pack.apply(db, db.get(Company, branch))
    assert db.get(Company, benta).primary_email is None and count(db, Email, Email.company_id == benta) == 0
    assert roles(db, branch) == {} and db.get(Company, branch).primary_phone is None
    entries = [Record(org=[], excerpt="https://news.example/brand-voice/omega-foods-goes-global"),
               Record(org=[], excerpt="https://news.example/business/omega-foods-expands-to-iraq")]
    assert [r.excerpt for r in news.matching_articles(entries, ["Omega Foods"], NOW)] == [entries[1].excerpt]
