"""Step 6.3 contributions: business cards, professional e-mail signatures, meeting contacts and contacts added on a
company's page enter the same graph - attributed, scoped (organization / managers / private), corroborated across
independent contributors (never duplicated), a prediction attested by a real record, removable without touching
public evidence, and a connector-neutral sync. No real connector: a fake one."""

from sqlalchemy import func, select

from app.models import ContactEvidence, Email, Person, Phone, Source
from app.models.enums import UserRole
from app.services import contact_intelligence as contacts
from app.services import contributions
from tests.test_contacts import omega
from tests.test_enrichment import research, site  # noqa: F401 - the mocked-web fixture

SIGNATURE = """Best regards,

Tony Rizk
Operations Manager
Omega Foods SAL
M: +961 3 777 888 | T: +961 8 800 801 ext. 15
tony.rizk@omegafoods.example
www.omegafoods.example"""


def people(client, company_id):
    return {p["person"]["full_name"]: p for p in client.get(f"/companies/{company_id}/people").json()}


def test_signature_parsing():
    entry = contributions.parse_signature(SIGNATURE.split("\n\n", 1)[1])
    assert entry == {"person": "Tony Rizk", "title": "Operations Manager", "company": "Omega Foods SAL",
                     "mobile": "+961 3 777 888", "phone": "+961 8 800 801", "extension": "15",
                     "email": "tony.rizk@omegafoods.example", "website": "www.omegafoods.example"}
    assert contributions.parse_signature("Thanks\nJohn") is None  # no contact field: nothing to contribute


def test_cards_signatures_meetings_corroboration_and_visibility(client_for, db, site):  # noqa: F811
    agent, alice = client_for(UserRole.SALES_AGENT)
    company_id = omega(agent, site)
    research(agent, company_id)
    contacts.run(db, company_id)  # Tony Rizk has a predicted address
    # an e-mail signature attests the prediction: published, the prediction kept in its trail
    report = contributions.ingest(db, system="EMAIL_SIGNATURE", file_name="sig.txt", raw=SIGNATURE.encode(),
                                  owner_user_id=alice.id, apply=True)
    assert report["predicted_to_corroborated"] == 1 and report["person_exact"] + report.get("person_strong", 0) == 1
    tony = db.scalar(select(Email).where(Email.email == "tony.rizk@omegafoods.example"))
    assert (tony.status, tony.provenance) == ("published", "contributed")
    assert {e.kind for e in db.scalars(select(ContactEvidence).where(ContactEvidence.email_id == tony.id))} == {
        "predicted", "email_signature_published"}
    assert db.scalar(select(Phone.phone_type).where(Phone.phone.like("+961 3 777 888"))) == "business_mobile"
    # a second, independent contributor's business card: the same person and address, corroborated, not duplicated
    bob_client, bob = client_for(UserRole.SALES_AGENT, email="bob@tecomsa.example")
    card = ("BEGIN:VCARD\nVERSION:3.0\nFN:Tony Rizk\nORG:Omega Foods\nTITLE:Operations Manager\n"
            "EMAIL:tony.rizk@omegafoods.example\nTEL;TYPE=CELL:+961 3 777 888\nEND:VCARD\n")
    dry = contributions.ingest(db, system="BUSINESS_CARD", file_name="cards.vcf", raw=card.encode(),
                               owner_user_id=bob.id)
    assert db.scalar(select(func.count()).select_from(Source).where(Source.source_type == "business_card")) == 0
    applied = contributions.ingest(db, system="BUSINESS_CARD", file_name="cards.vcf", raw=card.encode(),
                                   owner_user_id=bob.id, apply=True)
    assert applied["emails_corroborated"] == 1 == dry["emails_corroborated"]
    assert db.scalar(select(func.count()).select_from(Person).where(Person.full_name == "Tony Rizk")) == 1
    best = people(agent, company_id)["Tony Rizk"]["contacts"][0]
    assert best["kind"] == "corroborated_email" and people(agent, company_id)["Tony Rizk"]["contactable"]
    from scripts.contact_coverage import network_metrics

    assert network_metrics()["emails_with_2plus_contributors"] == 1
    # a meeting contact: attendance links a known person to an address, never creates an unknown one
    meeting = "Attendee,Email,Company,Meeting Date\nRana Saad,rana.s@omegafoods.example,Omega Foods,2026-09-20\n" \
              "Stranger Danger,s.d@omegafoods.example,Omega Foods,2026-09-20\n"
    m = contributions.ingest(db, system="MEETING_CONTACT", file_name="meeting.csv", raw=meeting.encode(),
                             owner_user_id=alice.id, apply=True)
    assert (m["person_exact"], m["rejected_no_title_unknown_person"]) == (1, 1)
    assert db.scalar(select(func.count()).select_from(Person).where(Person.full_name == "Stranger Danger")) == 0
    # private: only its contributor sees it (not even a manager)
    private_card = card.replace("Tony Rizk", "Lina Khoury").replace("tony.rizk", "lina.private") \
        .replace("Operations Manager", "Finance Director").replace("777 888", "111 999")
    contributions.ingest(db, system="BUSINESS_CARD", file_name="mine.vcf", raw=private_card.encode(),
                         owner_user_id=bob.id, visibility="private", apply=True)
    manager, _ = client_for(UserRole.SALES_MANAGER, email="manager@tecomsa.example")
    see = lambda c: [x["email"] for x in people(c, company_id)["Lina Khoury"]["emails"]]  # noqa: E731
    assert "lina.private@omegafoods.example" not in see(manager) and "lina.private@omegafoods.example" not in see(agent)
    assert bob_client.get(f"/companies/{company_id}/people").status_code == 404  # alice's company
    manager.patch(f"/companies/{company_id}/owner", json={"owner_user_id": bob.id})  # reassigned to bob
    assert "lina.private@omegafoods.example" in see(bob_client)


def test_suppression_keeps_public_evidence_and_blocks_reimport(client_for, db, site):  # noqa: F811
    agent, alice = client_for(UserRole.SALES_AGENT)
    company_id = omega(agent, site)
    research(agent, company_id)
    contacts.run(db, company_id)  # Joseph Haddad's address, published on the company's contact page
    rows = "Company,Name,Job Position,Email,Mobile\n" \
           "Omega Foods,Joseph Haddad,Chief Executive Officer,joseph.haddad@omegafoods.example,03 444 555\n" \
           "Omega Foods,Maya Nasr,IT Director,maya.nasr@omegafoods.example,\n"
    contributions.ingest(db, system="CSV_IMPORT", file_name="c.csv", raw=rows.encode(), owner_user_id=alice.id,
                         apply=True)
    maya_source = db.scalar(select(Source).where(Source.source_type == "internal_seed",
                                                 Source.external_reference.like("%maya%")))
    joseph_source = db.scalar(select(Source).where(Source.source_type == "internal_seed",
                                                   Source.external_reference.like("%joseph%")))
    removed = contributions.suppress(db, joseph_source.id, user_id=alice.id, reason="contact asked to be removed")
    # Joseph's published address (on the company's own contact page) stays; the CRM-only mobile goes
    assert db.scalar(select(Email.status).where(Email.email == "joseph.haddad@omegafoods.example")) == "published"
    assert db.scalar(select(func.count()).select_from(Phone).where(Phone.phone == "03 444 555")) == 0
    assert removed["emails_kept_other_evidence"] == 1 and removed["roles_kept_other_evidence"] == 1
    contributions.suppress(db, maya_source.id, user_id=alice.id, reason="retention")
    assert "Maya Nasr" not in people(agent, company_id)  # known only from that record: gone
    again = contributions.ingest(db, system="CSV_IMPORT", file_name="c.csv", raw=rows.encode(),
                                 owner_user_id=alice.id, apply=True)
    assert again["suppressed_skipped"] == 2  # never imported again


def test_page_contribution_and_connector_sync(client_for, db, site):  # noqa: F811
    agent, alice = client_for(UserRole.SALES_AGENT)
    company_id = omega(agent, site)
    research(agent, company_id)
    r = agent.post(f"/companies/{company_id}/contributions", json={"channel": "EMAIL_SIGNATURE",
                                                                  "signature": SIGNATURE, "visibility": "managers"})
    assert r.status_code == 201 and r.json()["unique_people"] == 1
    assert people(agent, company_id)["Tony Rizk"]["contacts"][0]["label"] == "Contributed business contact"
    bad = agent.post(f"/companies/{company_id}/contributions", json={"person": "Nobody Known"})
    assert bad.status_code in (400, 409, 422)  # no title and not a known person: nothing created

    class Fake(contributions.BusinessContactConnector):
        def meeting_participants(self):
            return [{"person": "Rana Saad", "email": "rana.saad@omegafoods.example", "company": "Omega Foods"}]

        def delivery_events(self):
            return [{"event": "replied", "email": "tony.rizk@omegafoods.example", "event_key": "m-1"},
                    {"event": "replied", "email": "tony.rizk@omegafoods.example", "event_key": "m-1"}]

    before = db.scalar(select(func.count()).select_from(Email))
    dry = contributions.sync(db, Fake(), alice)
    assert dry["events_applied"] == 0 and db.scalar(select(func.count()).select_from(Email)) == before
    done = contributions.sync(db, Fake(), alice, apply=True)
    assert done["meetings"]["person_exact"] == 1 and done["events_applied"] == 1  # the repeated reply: once
    from scripts.contact_coverage import measure

    public, proprietary = measure([company_id], public=True), measure([company_id])
    assert proprietary["departments"]["Operations"]["people_contactable"] ==         public["departments"]["Operations"]["people_contactable"] + 1  # Tony: contributed + confirmed, not public
    assert db.scalar(select(Email.status).where(Email.email == "tony.rizk@omegafoods.example")) == "confirmed"


def test_log_a_call_saves_the_manager_with_mobile_and_extension(client_for, db, site):  # noqa: F811
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = omega(agent, site)
    r = agent.post(f"/companies/{company_id}/contributions", json={
        "channel": "SALES_CONFIRMED", "person": "Karim Aoun", "title": "IT Manager", "mobile": "03 123 456",
        "phone": "+961 8 800 801", "extension": "214"})
    assert r.status_code == 201, r.text
    karim = db.scalar(select(Person.id).where(Person.full_name == "Karim Aoun"))
    kinds = set(db.scalars(select(Phone.phone_type).where(Phone.person_id == karim)))
    assert "business_mobile" in kinds and kinds & {"office_extension", "direct_business_phone"}
    # ...and the export carries him with his number, as Excel reads it (BOM, one row per person)
    csv_text = agent.get("/companies/export.csv").text
    assert csv_text.startswith("﻿Company,") and "Karim Aoun,IT Manager" in csv_text and "123456" in csv_text.replace(" ", "")
    other, _ = client_for(UserRole.SALES_AGENT)
    assert "Karim Aoun" not in other.get("/companies/export.csv").text  # another salesperson's company: not exported


def test_a_page_contribution_cannot_claim_an_import_provenance(client_for, db, site):  # noqa: F811
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = omega(agent, site)
    for channel in ("ODOO_CRM", "LICENSED_DIRECTORY", "LUSHA", "CSV_IMPORT"):
        r = agent.post(f"/companies/{company_id}/contributions",
                       json={"channel": channel, "person": "Karim Aoun", "title": "IT Manager", "mobile": "03 123 456"})
        assert r.status_code == 422, (channel, r.text)
