"""Contact intelligence (Step 6): published contact points attached only with explicit evidence, company mailboxes
kept the company's, e-mail patterns observed on real addresses, bounded predictions labelled PREDICTED, MX / mailbox
verification (verified / catch-all / invalid / unknown), phone classification (mobile / direct / extension /
switchboard), human-confirmed data untouched, terminal states. Websites and mail servers are mocked."""

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.models import Company, CompanyEmailPattern, Email, Person, Phone
from app.models.enums import UserRole
from app.services import contact_intelligence as contacts
from app.services import jobs
from tests.test_enrichment import new_company, research, site  # noqa: F401 - the mocked-web fixture

HOME = """<html><head><title>Omega Foods | Home</title></head><body><nav><a href="/team">Our team</a>
<a href="/contact">Contact</a></nav><p>Omega Foods makes snacks in Zahle. Call +961 8 800 800.</p></body></html>"""
TEAM = """<html><title>Our team</title><body><h1>Management</h1>
<h3>Joseph Haddad</h3><p>Chief Executive Officer</p>
<h3>Rana Saad</h3><p>Procurement Manager</p><p>Mobile: 03 123 456</p>
<h3>Karim Aoun</h3><p>IT Manager</p><p>Tel: 08 800 800</p>
<h3>Lina Khoury</h3><p>Finance Director</p><p>Tel: 08 800 801 ext. 214</p>
<h3>Tony Rizk</h3><p>Operations Manager</p></body></html>"""
CONTACT = """<html><title>Contact us</title><body><p>General enquiries: info@omegafoods.example</p>
<p>Sales: sales@omegafoods.example</p><p>Write to our CEO office: joseph.haddad@omegafoods.example</p>
<p>Main line +961 8 800 800</p></body></html>"""
OMEGA = {"/": HOME, "/team": TEAM, "/contact": CONTACT}


def omega(client, site, pages=OMEGA) -> int:  # noqa: F811
    site.sites["www.omegafoods.example"] = dict(pages)
    return new_company(client, name="Omega Foods", website="https://www.omegafoods.example",
                       primary_phone="+961 8 800 800")


def emails(db, company_id) -> dict[str, tuple[str, str]]:
    db.expire_all()
    return {e.email: (e.status, e.provenance) for e in db.scalars(select(Email).where(
        Email.company_id == company_id, Email.person_id.is_not(None)))}


def person_id(db, name) -> int:
    return db.scalar(select(Person.id).where(Person.full_name == name))


def test_published_pattern_predicted_and_company_mailboxes(client_for, db, site):  # noqa: F811
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = omega(agent, site)
    research(agent, company_id)
    result = contacts.run(db, company_id)
    assert result["status"] == "completed"
    found = emails(db, company_id)
    # published on the contact page and spelling the CEO's full name: his, published
    assert found["joseph.haddad@omegafoods.example"] == ("published", "public")
    # the company's mailboxes never become a person's
    assert not any(e.startswith(("info@", "sales@")) for e in found)
    # the observed pattern (first.last) drives one prediction per decision-maker, labelled predicted
    assert found["rana.saad@omegafoods.example"] == ("predicted", "predicted")
    assert found["tony.rizk@omegafoods.example"] == ("predicted", "predicted")
    assert sum(1 for e in found if e.startswith("rana")) == 1
    pattern = db.scalar(select(CompanyEmailPattern))
    assert (pattern.pattern, pattern.sample_count) == ("first.last", 1)
    predicted = db.scalar(select(Email).where(Email.email == "rana.saad@omegafoods.example"))
    assert predicted.last_verified_at is None and "observed company pattern" in predicted.evidence
    # the People API: strongest channel first, a prediction never counted as contactable
    people = {p["person"]["full_name"]: p for p in agent.get(f"/companies/{company_id}/people").json()}
    best = people["Joseph Haddad"]["contacts"][0]
    assert {k: best[k] for k in ("kind", "label", "value")} == {"kind": "published_email", "label": "Published",
                                                                 "value": "joseph.haddad@omegafoods.example"}
    assert best["since"] and best["stale"] is False  # how fresh: last confirmed / seen
    assert people["Tony Rizk"]["contactable"] is False
    assert people["Tony Rizk"]["contacts"][0]["label"] == "Predicted"
    # a re-run never reads its own prediction back as a published address
    contacts.run(db, company_id, force=True)
    assert emails(db, company_id)["rana.saad@omegafoods.example"] == ("predicted", "predicted")


def test_phone_classification_switchboard_extension_and_mobile(client_for, db, site):  # noqa: F811
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = omega(agent, site)
    research(agent, company_id)
    contacts.run(db, company_id)
    db.expire_all()
    kinds = {db.get(Person, p.person_id).full_name: p.phone_type for p in db.scalars(select(Phone).where(
        Phone.person_id.is_not(None)))}
    assert kinds["Rana Saad"] == "business_mobile"  # 03: a Lebanese mobile range
    assert kinds["Karim Aoun"] == "company_switchboard"  # the company's own main line: never his direct line
    assert kinds["Lina Khoury"] == "office_extension"
    people = {p["person"]["full_name"]: p for p in agent.get(f"/companies/{company_id}/people").json()}
    assert people["Rana Saad"]["contacts"][0]["kind"] == "business_mobile" and people["Rana Saad"]["contactable"]
    assert people["Karim Aoun"]["contacts"][0]["kind"] != "direct_business_phone"  # switchboard not shown as his
    assert contacts.classify_phone("+961 1 234567", company_numbers=set()) == "direct_business_phone"
    assert contacts.classify_phone("71 555 444", company_numbers=set(), context="WhatsApp") == "whatsapp"


def test_candidates_are_bounded_and_conservative_without_a_pattern():
    assert contacts.name_parts("Dr. Joseph El Haddad") == ("joseph", "haddad")
    assert contacts.name_parts("جوزيف حداد") is None  # no Latin name: nothing predicted
    assert contacts.pattern_of("jhaddad", "joseph", "haddad") == "flast"
    options = contacts.candidates("joseph", "haddad", "abc.example", [])
    assert [a for a, _ in options] == ["joseph.haddad@abc.example", "jhaddad@abc.example", "joseph@abc.example",
                                       "josephhaddad@abc.example"]
    assert len(contacts.candidates("joseph", "haddad", "abc.example", ["flast", "first.last"])) <= 5
    assert contacts.candidates("joseph", "haddad", "abc.example", ["flast"])[0][0] == "jhaddad@abc.example"


@pytest.mark.parametrize("probe,expected", [
    ({"__catch_all__": "catch_all"}, "catch_all"),
    ({"rana.saad@omegafoods.example": "verified"}, "verified"),
    ({}, "invalid_all"),
    ({"rana.saad@omegafoods.example": "unknown"}, "predicted"),
])
def test_mailbox_verification_states(client_for, db, site, monkeypatch, probe, expected):  # noqa: F811
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = omega(agent, site)
    research(agent, company_id)
    monkeypatch.setattr(get_settings(), "email_smtp_verification", True)

    def fake_probe(host, domain, addresses):
        if "__catch_all__" in probe:
            return {a: "catch_all" for a in addresses}
        return {a: probe.get(a, "invalid") for a in addresses}
    monkeypatch.setattr(contacts.SmtpEmailVerifier, "_probe", staticmethod(fake_probe))
    contacts.run(db, company_id)
    rana = {e: s for e, s in emails(db, company_id).items() if e.startswith("rana")}
    if expected == "invalid_all":
        assert rana == {}  # every candidate refused: nothing shown
    else:
        assert list(rana.values()) == [(expected, "verified" if expected == "verified" else "predicted")]
    if expected == "verified":
        row = db.scalar(select(Email).where(Email.email == "rana.saad@omegafoods.example"))
        assert row.last_verified_at is not None and row.verification["smtp"] == "verified"


def test_mailbox_check_uses_configured_sender(monkeypatch):
    senders = []

    class FakeSMTP:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def ehlo_or_helo_if_needed(self): pass
        def mail(self, sender): senders.append(sender); return (250, b"ok")
        def rcpt(self, address): return (550, b"5.1.1 user unknown")
        def rset(self): pass
    monkeypatch.setattr(contacts.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(get_settings(), "email_smtp_mail_from", "verify@tecomsa.example")
    contacts.SmtpEmailVerifier._probe("mx.example", "example", ["a@example"])
    monkeypatch.setattr(get_settings(), "email_smtp_mail_from", "")
    contacts.SmtpEmailVerifier._probe("mx.example", "example", ["a@example"])
    assert senders == ["verify@tecomsa.example", ""]  # "" = the null sender <>


@pytest.mark.parametrize("code,reply,invalid", [
    (550, b"5.1.1 User does not exist", True),
    (550, b"<x@cumberland.com.lb>, Recipient unknown", True),  # real reply, no enhanced code
    (550, b"5.7.1 Client host blocked using Spamhaus", False),
    (550, b"Mail rejected by <Zoho Mail> for policy reasons", False),
])
def test_no_such_user_vs_policy_refusal(code, reply, invalid):
    assert contacts._no_such_user(code, reply) is invalid


def test_no_mail_setup_nothing_predicted_and_human_contacts_untouched(client_for, db, site, monkeypatch):  # noqa: F811
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = omega(agent, site)
    research(agent, company_id)
    tony = person_id(db, "Tony Rizk")
    db.add(Email(person_id=tony, company_id=company_id, email="tony@omega-private.example", email_type="work",
                 status="published", provenance="human_confirmed"))
    db.commit()
    monkeypatch.setattr(contacts, "mx_hosts", lambda domain: [])  # the domain receives no mail
    contacts.run(db, company_id)
    found = emails(db, company_id)
    assert not any(status == "predicted" for status, _ in found.values())
    assert found["tony@omega-private.example"] == ("published", "human_confirmed")


def test_contact_research_ends_queues_once_and_never_invents_phones(client_for, db, site, monkeypatch):  # noqa: F811
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = omega(agent, site)
    research(agent, company_id)
    phones_before = db.scalar(select(func.count()).select_from(Phone))
    company = db.get(Company, company_id)
    assert contacts.request(db, company, 5) is True and contacts.request(db, company, 5) is False
    db.commit()
    monkeypatch.setattr(get_settings(), "contact_job_seconds", 0)
    while jobs.run_next((jobs.CONTACT,)):
        pass
    db.expire_all()
    assert db.get(Company, company_id).contact_status == "timed_out"  # bounded: a terminal state
    assert db.scalar(select(func.count()).select_from(Phone)) == phones_before  # no number is ever inferred
    assert not any("linkedin" in r for r in site.requests)


def test_team_pages_from_the_sitemap_and_never_a_soft_404(client_for, db, site):  # noqa: F811
    agent, _ = client_for(UserRole.SALES_AGENT)
    home = HOME.replace('<a href="/team">Our team</a>', "")
    leadership = TEAM.replace("<title>Our team</title>", "<title>Leadership | Omega Foods</title>")
    site.sites["www.omegafoods.example"] = {
        "/": home, "/contact": CONTACT, "/leadership": leadership,
        "/sitemap.xml": "<urlset><url><loc>https://www.omegafoods.example/leadership</loc></url>"
                        "<url><loc>https://www.omegafoods.example/products</loc></url></urlset>"}
    company_id = new_company(agent, name="Omega Foods", website="https://www.omegafoods.example")
    research(agent, company_id)
    names = {p["person"]["full_name"] for p in agent.get(f"/companies/{company_id}/people").json()}
    assert {"Joseph Haddad", "Rana Saad"} <= names  # an unlinked team page, found in the sitemap
    soft = {path: home for path in ("/", "/team", "/our-team", "/management", "/leadership", "/about-us/team",
                                    "/board-of-directors")}  # a site answering every address with its home page
    site.sites["www.deltafoods.example"] = soft
    other = new_company(agent, name="Delta Foods", website="https://www.deltafoods.example")
    research(agent, other)
    from app.models import CompanyWebPage
    assert db.scalar(select(func.count()).select_from(CompanyWebPage).where(
        CompanyWebPage.company_id == other, CompanyWebPage.page_type == "team")) == 0
