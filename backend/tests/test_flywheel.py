"""Step 6.1 contact flywheel: high-confidence predictions only on >= 2 real published addresses of the pattern, sales
feedback applied to the graph (delivered / bounced / replied, number confirmed / wrong, person left / wrong person)
and protected from research, TECOMSA internal seeds resolved to existing companies with owner-only visibility."""

from sqlalchemy import func, select

from app.models import Company, CompanyPerson, ContactFeedback, Email, Person, Phone
from app.models.enums import UserRole
from app.services import contact_intelligence as contacts
from app.services import contributions
from tests.test_contacts import CONTACT, HOME, TEAM, omega
from tests.test_enrichment import research, site  # noqa: F401 - the mocked-web fixture

TWO_SAMPLES = CONTACT.replace("</body>", "<p>Procurement: rana.saad@omegafoods.example</p></body>")


def status_of(db, address):
    db.expire_all()
    return db.scalar(select(Email.status).where(Email.email == address))


def people(client, company_id):
    return {p["person"]["full_name"]: p for p in client.get(f"/companies/{company_id}/people").json()}


def test_high_confidence_prediction_needs_two_real_samples(client_for, db, site):  # noqa: F811
    agent, _ = client_for(UserRole.SALES_AGENT)  # (one published address: an ordinary prediction, test_contacts)
    one = omega(agent, site, {"/": HOME, "/team": TEAM, "/contact": TWO_SAMPLES})
    research(agent, one)
    contacts.run(db, one)
    assert status_of(db, "tony.rizk@omegafoods.example") == "high_confidence_predicted"
    tony = people(agent, one)["Tony Rizk"]
    assert tony["contacts"][0]["label"] == "Predicted (high confidence)" and not tony["contactable"]


def test_sales_feedback_events_update_the_graph(client_for, db, site):  # noqa: F811
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = omega(agent, site)
    research(agent, company_id)
    contacts.run(db, company_id)
    post = lambda **body: agent.post(f"/companies/{company_id}/contact-feedback", json=body)  # noqa: E731
    tony = db.scalar(select(Email).where(Email.email == "tony.rizk@omegafoods.example"))
    assert post(event="delivered", email_id=tony.id).status_code == 201
    assert status_of(db, tony.email) == "high_confidence_predicted"
    assert post(event="replied", email_id=tony.id).status_code == 201
    assert status_of(db, tony.email) == "confirmed"
    contacts.run(db, company_id, force=True)  # research never downgrades what a reply confirmed
    assert status_of(db, tony.email) == "confirmed" and people(agent, company_id)["Tony Rizk"]["contactable"]
    rana = db.scalar(select(Email).where(Email.email == "rana.saad@omegafoods.example"))
    post(event="hard_bounce", email_id=rana.id)
    assert status_of(db, rana.email) == "invalid"
    assert all(c["value"] != rana.email for c in people(agent, company_id)["Rana Saad"]["contacts"])
    mobile = db.scalar(select(Phone).where(Phone.phone_type == "business_mobile"))
    post(event="wrong_number", phone_id=mobile.id)
    assert not people(agent, company_id)["Rana Saad"]["contacts"] or all(
        c["kind"] != "business_mobile" for c in people(agent, company_id)["Rana Saad"]["contacts"])
    roles = {r.person_id: r for r in db.scalars(select(CompanyPerson))}
    karim = next(r for r in roles.values() if db.get(Person, r.person_id).full_name == "Karim Aoun")
    lina = next(r for r in roles.values() if db.get(Person, r.person_id).full_name == "Lina Khoury")
    post(event="person_left_company", company_person_id=karim.id)
    post(event="wrong_person", company_person_id=lina.id)
    post(event="title_changed", company_person_id=roles[tony.person_id].id, value="Operations Director")
    research(agent, company_id)  # the team page still lists them: research never undoes a person's verdict
    agent.get(f"/companies/{company_id}/people")
    db.expire_all()
    assert db.get(CompanyPerson, karim.id).employment_status == "former"
    assert db.get(CompanyPerson, lina.id).confidence == 0
    assert db.get(CompanyPerson, roles[tony.person_id].id).job_title == "Operations Director"
    assert db.scalar(select(func.count()).select_from(ContactFeedback)) == 7
    assert post(event="probe", email_id=tony.id).status_code in (400, 422)


SEED = """Partner ID,Company,Contact Name,Job Position,Email,Mobile,Website
od-17,Omega Foods SAL,Nadine Frem,Chief Financial Officer,nadine.frem@omegafoods.example,03 555 666,
od-18,Unknown Traders,Sami Kassab,General Manager,sami@unknown.example,,
od-19,Delta Group,Maya Haddad,IT Manager,maya@gmail.com,,
"""


def test_internal_seed_resolution_provenance_and_visibility(client_for, db, site):  # noqa: F811
    owner, owner_user = client_for(UserRole.SALES_AGENT)
    company_id = omega(owner, site)
    research(owner, company_id)
    report = contributions.ingest(db, system="ODOO_CRM", file_name="contacts.csv", raw=SEED.encode(),
                                  owner_user_id=owner_user.id, visibility="managers", apply=True)
    assert (report["person_new"], report["company_unmatched"], report["companies_matched"]) == (1, 2, 1)
    email = db.scalar(select(Email).where(Email.email == "nadine.frem@omegafoods.example"))
    assert (email.provenance, email.visibility, email.owner_user_id) == ("internal_crm", "managers", owner_user.id)
    assert db.scalar(select(Phone.phone_type).where(Phone.person_id == email.person_id)) == "business_mobile"
    assert people(owner, company_id)["Nadine Frem"]["contactable"]
    other, _ = client_for(UserRole.SALES_AGENT, email="other.agent@tecomsa.example")
    assert "Nadine Frem" not in people(other, company_id)  # another salesperson's restricted contact
    manager, _ = client_for(UserRole.SALES_MANAGER, email="manager@tecomsa.example")
    assert people(manager, company_id)["Nadine Frem"]["contacts"][0]["label"] == "TECOMSA CRM"
    again = contributions.ingest(db, system="ODOO_CRM", file_name="contacts.csv", raw=SEED.encode(),
                                 owner_user_id=owner_user.id, visibility="managers", apply=True)
    assert again["person_exact"] == 1 and db.scalar(select(func.count()).select_from(Person).where(
        Person.full_name == "Nadine Frem")) == 1
    contacts.run(db, company_id, force=True)  # research never touches TECOMSA CRM contacts
    assert db.scalar(select(Email.provenance).where(Email.id == email.id)) == "internal_crm"
    assert db.scalar(select(func.count()).select_from(Company)) == 1  # nothing created from a file
    from scripts.contact_coverage import contributions as source_contributions

    sources = source_contributions([company_id])  # source contribution: the internal seed made the company contactable
    assert sources["internal_seed"]["contactable_companies"] == 1 and sources["internal_seed"]["decision_makers"] == 1
