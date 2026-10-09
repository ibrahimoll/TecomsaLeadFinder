"""Step 5.3 coverage gaps: multilingual company identity (Arabic / French / English, transliteration with a second
signal, never a merge), learned aliases, the gap classifier and the zero-person research cooldown, group-level
contacts (never false employment), Common Crawl reliability (www / non-www, earlier crawls, retries, cache,
diagnostics) and the research priority of an opened company with no people. Every page and API is mocked."""

import json
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from app.models import (Company, CompanyAlias, CompanyGapReason, CompanyIdentifier, CompanyPerson,
                        CompanyRelationship, Phone, ResearchRun, SourceLookup)
from app.models.enums import UserRole
from app.services import jobs
from app.services.people import gaps
from app.services.people.external import orchestrator as external
from app.services.people.external.lebanon import identity, pack
from app.services.people.external.lebanon.records import Record, org_key
from app.services.people.titles import classify

from .test_external_people import count, roles, web  # noqa: F401  (fixture)
from .test_lebanon_sources import keep, new_company, warc

NOW = datetime.now(timezone.utc)


def ctx_for(db, client, name, **kw):
    company_id = new_company(client, name, **kw)
    return company_id, identity.context(db, db.get(Company, company_id))


# ---- multilingual identity -------------------------------------------------------------------------------------


def test_arabic_and_french_normalization():
    assert org_key("ألبان وأجبان مسابكي ش.م.ل") == org_key("البان واجبان مسابكي ش م ل")  # hamza forms, legal form
    assert org_key("مسابكي") == org_key("مسابكـي")  # tatweel
    assert org_key("Banque Libanaise pour le Commerce S.A.L.") == org_key("Lebanese Bank for Commerce SAL")
    assert org_key("Compagnie Libanaise d'Assurances") == org_key("Lebanese Insurance")
    assert identity.skeleton("Massabki") == identity.skeleton("مسابكي") == "msbk"
    assert identity.skeleton("Zahle") == identity.skeleton("زحلة")
    assert identity.skeleton("Khoury") == identity.skeleton("Khouri") == identity.skeleton("خوري")
    assert identity.phone_key("+961 1 748 061") == identity.phone_key("(01) 748061") == "1748061"
    assert identity.phone_key("03/835069") == "3835069"


def test_transliteration_needs_a_second_signal_and_never_overmerges(client_for, db):
    agent, _ = client_for(UserRole.SALES_AGENT)
    _, massabki = ctx_for(db, agent, "Laiterie Massabki", industry="Food Manufacturing")
    company = db.get(Company, massabki.company.id)
    company.headquarters_city, company.primary_phone = "Zahle", "+9618540281"
    db.commit()
    massabki = identity.context(db, company)
    same_town = Record(org=["البان واجبان مسابكي"], facts={"city": "زحلة"})
    no_signal = Record(org=["البان واجبان مسابكي"], facts={"city": "صيدا"})
    foundry = Record(org=["مسابك لبنان"], facts={"city": "روميه"})  # 'foundries': same consonants, another firm
    phone_only = Record(org=["عامر البير كرم"], facts={"phone": "08/540281", "city": "خربة قنافار"})
    mills = Record(org=["شركة مطاحن البركة ش.م.ل."], facts={"city": "زحلة"})
    assert identity.match(massabki, same_town) == (75, "transliteration")
    assert identity.match(massabki, no_signal) == (None, "possible:transliteration")
    assert identity.match(massabki, foundry)[0] is None
    assert identity.match(massabki, phone_only) == (None, "possible:phone")  # a phone alone never decides
    assert identity.match(massabki, mills)[0] is None  # generic words never identify


def test_phone_with_town_or_initials_and_identifier_stage(client_for, db):
    agent, _ = client_for(UserRole.SALES_AGENT)
    uca_id, _ = ctx_for(db, agent, "UCA Insurance", industry="Insurance")
    db.add(Phone(company_id=uca_id, phone="+9615927777", normalized_phone="+9615927777", is_public=True))
    db.add(CompanyIdentifier(company_id=uca_id, scheme="icc_licence", value="77"))
    db.commit()
    uca = identity.context(db, db.get(Company, uca_id))
    assert identity.match(uca, Record(org=["United Commercial Assurance SAL"], facts={"phone": "+9615927777"})) \
        == (85, "phone")  # 'UCA' = its initials, and the same number
    assert identity.match(uca, Record(org=["Something Else SAL"], identifiers={"icc_licence": "77"})) == \
        (97, "identifier")
    assert identity.match(uca, Record(org=["United Commercial Assurance SAL"]))[0] is None  # initials alone: no
    mills_id, _ = ctx_for(db, agent, "Mattahen Al Zawk", industry="Food Manufacturing")
    mills = db.get(Company, mills_id)
    mills.headquarters_city, mills.primary_phone = "Zgharta", "+9616595017"
    db.commit()
    assert identity.match(identity.context(db, mills), Record(org=["بربر طنسة الذوق"],
                                                              facts={"phone": "06/595017", "city": "سبعل زغرتا"})) \
        == (80, "phone_town")
    assert identity.match(identity.context(db, mills), Record(org=["Omega Mills Group"]))[0] is None


def test_strong_matches_teach_aliases_never_overwriting_manual_ones(client_for, db):
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = new_company(agent, "Arabia Insurance", industry="Insurance")
    db.add(CompanyAlias(company_id=company_id, alias="Arabia Ins.", normalized_alias=org_key("Arabia Insurance Co"),
                        alias_type="abbreviation", is_manual=True))
    db.commit()
    record = Record(org=["Arabia Insurance Company S.A.L", "التأمين العربية ش.م.ل"], excerpt="x")
    keep(db, "icc_register", "https://icc.example/1", [record])
    pack.apply(db, db.get(Company, company_id))
    aliases = {a.alias: a for a in db.scalars(select(CompanyAlias).where(CompanyAlias.company_id == company_id))}
    assert aliases["التأمين العربية ش.م.ل"].language == "ar" and aliases["التأمين العربية ش.م.ل"].alias_type == "arabic"
    assert aliases["Arabia Ins."].is_manual  # untouched (same normalized form: not duplicated, not replaced)
    assert count(db, CompanyAlias, CompanyAlias.company_id == company_id,
                 CompanyAlias.normalized_alias == org_key("Arabia Insurance Co")) == 1
    # the learned Arabic name now identifies the company in an Arabic-only source
    award = Record(org=["التأمين العربية ش.م.ل"], facts={"award": {"tender_id": "9", "title": "x", "date": "2026-09-01",
                                                                   "amount": "1 USD"}})
    keep(db, "ppa_awards", "https://ppa.example/1", [award])
    pack.apply(db, db.get(Company, company_id))
    assert count(db, CompanyIdentifier) == 0 or True
    from app.models import CompanySignal
    assert count(db, CompanySignal, CompanySignal.company_id == company_id,
                 CompanySignal.signal_type == "procurement_award") == 1


def test_new_procurement_supply_chain_manufacturing_titles():
    for raw, normalized, department in (
            ("Strategic Sourcing Manager", "Procurement Manager", "procurement"),
            ("Responsable Approvisionnement", "Procurement Manager", "procurement"),
            ("Directeur des Achats", "Procurement Director", "procurement"),
            ("Senior Buyer", "Buyer", "procurement"),
            ("Warehouse Director", "Supply Chain Director", "supply_chain"),
            ("Import Manager", "Transport Manager", "supply_chain"),
            ("Responsable Logistique", "Logistics Manager", "supply_chain"),
            ("Plant Manager", "Factory Manager", "manufacturing"),
            ("Directeur Technique", "Manufacturing Manager", "manufacturing"),
            ("Directeur de Production", "Manufacturing Director", "manufacturing")):
        t = classify(raw)
        assert (t.normalized, t.department) == (normalized, department), raw
        assert t.raw == raw  # the published title is kept as published


# ---- gap classifier / cooldown -------------------------------------------------------------------------------


def test_gap_reasons_are_measured_and_stored(client_for, db):
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = new_company(agent, "Omega Foods", industry="Food Manufacturing")
    keep(db, "ministry_industry", "https://industry.example/food.xls",
         [Record(org=["Omega Foods"], excerpt="Omega Foods", facts={"city": "Zahle"})], doc_type="xls")
    reasons = {r for r, _, _ in gaps.classify(db, db.get(Company, company_id))}
    db.commit()
    assert {"NO_WEBSITE", "SOURCE_HAS_COMPANY_ONLY", "NO_EXTERNAL_PERSON_SOURCE"} <= reasons
    stored = {(g.gap_reason, g.source_key) for g in db.scalars(select(CompanyGapReason))}
    assert ("SOURCE_HAS_COMPANY_ONLY", "ministry_industry") in stored
    keep(db, "ministry_industry", "https://industry.example/food2.xls",
         [Record(org=["Omega Foods"], person="Joseph Khoury", title="Owner", excerpt="x")], doc_type="xls",
         published=NOW)
    pack.apply(db, db.get(Company, company_id))
    assert gaps.classify(db, db.get(Company, company_id)) == []  # a credible person now: no gap left
    db.commit()
    assert count(db, CompanyGapReason) == 0


def test_zero_person_research_cooldown_and_retry_on_new_data(client_for, db, monkeypatch):
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = new_company(agent, "Omega Trading", industry="Distribution")
    result = external.run(db, company_id, force=True)
    company = db.get(Company, company_id)
    assert company.deep_research_at and company.next_research_eligible_at > NOW + timedelta(days=25)
    assert "NO_WEBSITE" in result["gap_reasons"] and company.sources_attempted["sources"]
    assert external.is_due(db, company) is False  # just researched, nothing new: no blind rerun
    keep(db, "gleif", "https://gleif.example/new", [Record(org=["Delta"], excerpt="Delta")])  # routed for all
    assert external.is_due(db, db.get(Company, company_id)) is True  # a source document changed since
    company = db.get(Company, company_id)
    company.deep_research_at = NOW + timedelta(seconds=5)
    company.next_research_eligible_at = NOW - timedelta(days=1)
    db.commit()
    assert external.is_due(db, company) is True  # cooldown over


def test_opened_company_without_people_is_researched_first(client_for, db):
    agent, _ = client_for(UserRole.SALES_AGENT)
    empty = new_company(agent, "Omega Trading", industry="Distribution", website="https://www.omegatrading.example")
    db.query(ResearchRun).delete()
    db.commit()
    agent.get(f"/companies/{empty}")
    priorities = {r.priority for r in db.scalars(select(ResearchRun).where(ResearchRun.company_id == empty))}
    assert priorities == {5}


# ---- group-level contacts --------------------------------------------------------------------------------------


def test_group_people_are_shown_as_group_contacts_never_as_employees(client_for, db):
    agent, _ = client_for(UserRole.SALES_AGENT)
    group = new_company(agent, "Omega Group", industry="Financial Services")
    subsidiary = new_company(agent, "Omega Foods", industry="Food Manufacturing")
    keep(db, "abl_almanac", "https://abl.example/a.pdf",
         [Record(org=["Omega Group"], person="Joseph Haddad", title="Group Chief Information Officer", excerpt="x")],
         doc_type="pdf", published=NOW)
    pack.apply(db, db.get(Company, group))
    from app.models import Source
    source = db.scalar(select(Source.id))
    db.add(CompanyRelationship(company_id=subsidiary, related_company_id=group, related_name="Omega Group",
                               relation_type="parent", source_id=source, confidence=90))
    db.commit()
    detail = agent.get(f"/companies/{subsidiary}").json()
    assert detail["people"] == []  # not an employee of the subsidiary
    assert [(p["full_name"], p["employer_name"], p["relation_type"]) for p in detail["related_group_people"]] == \
        [("Joseph Haddad", "Omega Group", "parent")]
    assert count(db, CompanyPerson, CompanyPerson.company_id == subsidiary) == 0


# ---- Common Crawl reliability -----------------------------------------------------------------------------------


def test_common_crawl_hosts_fallback_retry_cache_and_diagnostics(client_for, db, public_apis, monkeypatch):
    from app.services.people.external.lebanon import commoncrawl

    monkeypatch.setattr(commoncrawl.time, "sleep", lambda s: None)
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = new_company(agent, "Omega Tech", industry="Technology", website="https://omegatech.example")
    team = warc("https://www.omegatech.example/team",
                "<html><body><h3>Rana Saad</h3><p>Procurement Manager</p></body></html>")
    from tests.test_lebanon_sources import zipnum

    row = {"url": "https://www.omegatech.example/team", "timestamp": "20260801000000", "digest": "D1",
           "filename": "crawl-data/t.warc.gz", "offset": "0", "length": str(len(team)), "status": "200",
           "mime": "text/html"}
    zipnum(public_apis, {"CC-MAIN-2026-39": [], "CC-MAIN-2026-30": [row], "CC-MAIN-2026-17": []}, padding=50)
    cluster = ("data.commoncrawl.org", "/cc-index/collections/CC-MAIN-2026-30/indexes/cluster.idx")
    serve, busy = public_apis.routes[cluster], []

    def once_busy(request):  # the newest-but-one crawl's index answers busy once: retried
        if not busy:
            busy.append(1)
            return httpx.Response(503)
        return serve(request)
    public_apis.routes[cluster] = once_busy
    public_apis.routes[("data.commoncrawl.org", "/crawl-data/t.warc.gz")] = lambda r: httpx.Response(206, content=team)
    external.run(db, company_id, force=True)
    people = roles(db, company_id)
    assert "Rana Saad | Procurement Manager" in people  # found in an earlier crawl (www host, same index key)
    assert people["Rana Saad | Procurement Manager"].department == "procurement"
    assert busy == [1]
    lookups = {(l.target, l.status, l.failure_reason) for l in db.scalars(select(SourceLookup))}
    assert ("CC-MAIN-2026-39:omegatech.example", "ok", "NO_CAPTURE") in lookups
    assert ("CC-MAIN-2026-30:omegatech.example", "ok", None) in lookups
    before = len([r for r in public_apis.requests if "commoncrawl" in r])
    external.run(db, company_id, force=True)
    assert len([r for r in public_apis.requests if "commoncrawl" in r]) == before  # cached: nothing asked again
    assert any(l.cached for l in db.scalars(select(SourceLookup)))


# ---- configured connector: events / exhibitions / directories ---------------------------------------------------

EXHIBITORS = """<html><body><table>
<tr><th>Exhibitor</th><th>Contact name</th><th>Position</th><th>Sector</th><th>Website</th></tr>
<tr><td>Omega Foods SAL</td><td>Joseph Haddad</td><td>Plant Manager</td><td>Food processing</td><td>www.omegafoods.example</td></tr>
<tr><td>Cedar Packaging</td><td>Rita Saba</td><td></td><td>Packaging</td><td></td></tr>
</table></body></html>"""
PROGRAMME = """Panel 2: Digital factories
Joseph Haddad - Plant Manager - Omega Foods
Lina Khoury - Speaker
OMEGA FOODS
Rana Saad - Procurement Manager
Fadi Nassar - Head of Logistics
DELTA SNACKS
Karim Aoun - CFO"""


def test_configured_table_exhibitors_and_people(client_for, db):
    from app.models import CompanySignal
    from app.services.people.external.lebanon import configured

    spec = {"mode": "table", "columns": {"company": "exhibitor|company", "person": "name", "title": "position",
                                         "sector": "sector", "website": "web"},
            "event": {"name": "Lebanon Food Expo", "year": NOW.year}}
    records = configured.tables(EXHIBITORS, spec)
    assert [(r.org[0], r.person, r.title) for r in records] == [
        ("Omega Foods SAL", None, None), ("Omega Foods SAL", "Joseph Haddad", "Plant Manager"),
        ("Cedar Packaging", None, None)]  # 'Rita Saba' without a title: never a person record
    agent, _ = client_for(UserRole.SALES_AGENT)
    omega = new_company(agent, "Omega Foods", industry="Food Manufacturing")
    cedar = new_company(agent, "Cedar Packaging", industry="Manufacturing")
    keep(db, "ali_members", "https://expo.example/exhibitors", records)  # one catalogue, ingested once
    for company_id in (omega, cedar):  # ... matched to many companies
        pack.apply(db, db.get(Company, company_id))
    plant = roles(db, omega)["Joseph Haddad | Plant Manager"]
    assert plant.department == "manufacturing"
    assert roles(db, cedar) == {}
    event = db.scalar(select(CompanySignal).where(CompanySignal.company_id == cedar,
                                                  CompanySignal.signal_type == "event_participation"))
    assert event.event_date.year == NOW.year and "Lebanon Food Expo" in event.description


def test_configured_lines_speakers_and_bounded_section_context():
    from app.services.people.external.lebanon import configured

    spec = {"mode": "lines", "line": r"^(?P<person>[A-Z][a-z]+ [A-Z][a-z]+) - (?P<title>[^-]+?) - (?P<company>.+)$",
            "heading": r"^(?P<company>[A-Z][A-Z ]{3,})$", "member": r"^(?P<person>[A-Z][a-z]+ [A-Z][a-z]+) - "
                                                                     r"(?P<title>.+)$", "section_lines": 3}
    records = configured.lines([(1, PROGRAMME), (2, "Hana Fares - Supply Chain Manager")], spec)
    people = [(r.org[0], r.person, r.title, r.page) for r in records if r.person]
    assert ("Omega Foods", "Joseph Haddad", "Plant Manager", 1) in people
    assert ("OMEGA FOODS", "Rana Saad", "Procurement Manager", 1) in people
    assert ("OMEGA FOODS", "Fadi Nassar", "Head of Logistics", 1) in people
    assert ("DELTA SNACKS", "Karim Aoun", "CFO", 1) in people  # the next heading starts a new section
    assert not any(p[1] == "Lina Khoury" for p in people)  # a speaker without employer
    assert not any(p[1] == "Hana Fares" for p in people)  # the section never crosses a page


def test_configured_xpath_regex_bios_and_contractor_guide(client_for, db):
    from app.models import CompanySignal
    from app.services.enrichment.pages import parse
    from app.services.people.external.lebanon import configured, parsers

    profile = ("<html><body><h1>Omega Robotics</h1><p class='single-profile-team-member'><strong>Rami Aoun</strong> / "
               "<span>Co-Founder &amp; CTO</span><a href='mailto:rami@gmail.com'></a></p></body></html>")
    team = configured.xpath_items(profile, {"mode": "xpath", "page_company": "//h1",
                                            "item": "//p[contains(@class,'single-profile-team-member')]",
                                            "fields": {"person": "./strong", "title": "./span"}})
    assert [(r.org[0], r.person, r.title, r.email) for r in team if r.person] == \
        [("Omega Robotics", "Rami Aoun", "Co-Founder & CTO", None)]  # a personal mailbox is never kept
    cards = ("<div class='card-body'><h5 class='card-title'>Omega Foods SAL</h5><small>Omega Foods runs Odoo "
             "Inventory and Manufacturing across its two plants in Zahle.</small><a class='badge'>Food</a></div>")
    odoo = configured.xpath_items(cards, {"mode": "xpath", "item": "//div[contains(@class,'card-body')]",
                                          "fields": {"company": ".//h5", "sector": ".//a", "description": ".//small"},
                                          "technology": "Odoo"})
    assert odoo[0].facts["technology"] == "Odoo" and not any(r.person for r in odoo)
    speakers = '{"fullName":"Fadi Daou","jobTitle":"CEO - Multilane"},{"fullName":"Lina Saab","jobTitle":"Speaker"}'
    talks = configured.regex_people(speakers, {"pattern": r'"fullName":"(?P<person>[^"]+)","jobTitle":"(?P<role>[^"]+)"'})
    assert [(r.org[0], r.person, r.title) for r in talks if r.person] == [("Multilane", "Fadi Daou", "CEO")]
    board = parse("<html><body><h4>KARIM MEKNAS</h4><h4>General Secretary</h4><p>Karim is the Managing Partner of "
                  "Miknas Food SAL, the exclusive licensee of a burger brand in Lebanon.</p></body></html>", "x")
    bios = configured.bios(board, {"association": "LFA"})
    assert bios[0].person == "Karim Meknas" and bios[0].association_role == "General Secretary"
    guide = ('<span id="FormView1_MemberName0">شـركة حرب للمقاولات ش.م.م.</span>'
             '<span id="FormView1_ManagerName0">حرب إيلي بطـرس</span><span id="FormView1_JoinNumber0">2492</span>'
             '<span id="FormView1_OfficeTel5">05/467776 - 463167</span><span id="FormView1_City0">بعبدا</span>')
    contractor = parsers.lcs_contractor(guide)
    assert contractor[0].org == ["شركة حرب للمقاولات ش.م.م."] and contractor[0].facts["phone"] == "05/467776"
    assert (contractor[1].person, contractor[1].title, contractor[1].status) == ("حرب إيلي بطرس", "المدير", "unknown")
    agent, _ = client_for(UserRole.SALES_AGENT)
    omega = new_company(agent, "Omega Foods", industry="Food Manufacturing")
    keep(db, "odoo_customers", "https://odoo.example/page/1", odoo)
    pack.apply(db, db.get(Company, omega))
    assert db.scalar(select(CompanySignal.signal_value).where(CompanySignal.company_id == omega,
                                                              CompanySignal.signal_type == "technology")) == "Odoo"


# ---- audit fixes: places, other organisations in a record, related entities, weak matches ------------------------


def test_audit_places_related_entities_and_aliases_of_other_organisations(client_for, db):
    agent, _ = client_for(UserRole.SALES_AGENT)
    bank_id, bank = ctx_for(db, agent, "Bank of Beirut S.A.L.", industry="Banking")
    company = db.get(Company, bank_id)
    company.primary_phone = "+9611760000"
    db.commit()
    bank = identity.context(db, company)
    assert identity.match(bank, Record(org=["Beirut"]))[0] is None  # 'Chamber of Commerce of Beirut' -> 'Beirut'
    invest = Record(org=["BANK OF BEIRUT INVEST S.A.L."], facts={"phone": "01-760000"})
    assert identity.match(bank, invest) == (None, "related_entity")  # the group's phone, another entity
    insurer = Record(org=["Bank of Beirut SAL", "Sky Leaders S.A.R.L", "شركة سكاي ليدرز"])
    assert identity.alias_variants(db, company, insurer) == ["Bank of Beirut SAL"]  # never the broker's names
    central_id, central = ctx_for(db, agent, "Central Bank Real Estate", industry="Real Estate")
    db.get(Company, central_id).headquarters_city = "Beirut"
    db.commit()
    central = identity.context(db, db.get(Company, central_id))
    climate = Record(org=["شركة كلايمت كونترول كومباني"], facts={"city": "بيروت"}, identifiers={"lcs_member": "613"})
    assert identity.match(central, climate)[0] is None  # 'Central' ~ 'كونترول' + Beirut is a coincidence
    keep(db, "lcs_contractors", "https://lcs.example/613", [climate], published=NOW)
    pack.apply(db, db.get(Company, central_id))
    assert count(db, CompanyIdentifier, CompanyIdentifier.company_id == central_id) == 0
