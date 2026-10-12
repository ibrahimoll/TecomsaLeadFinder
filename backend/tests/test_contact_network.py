"""Step 6.2 proprietary contact network: the TECOMSA import (dry run = apply's report with no write, idempotent,
company EXACT / STRONG / POSSIBLE / unmatched, person EXACT / STRONG / POSSIBLE / NEW, conflicts with confirmed
titles flagged, phones never given an assumed country code, owner / restricted visibility), the contact evidence
trail, idempotent feedback (event keys, address-level mail events), title history, freshness and the
public / proprietary metric separation."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.models import (Company, CompanyAlias, CompanyPerson, ContactEvidence, ContactFeedback, Email, Person, Phone,
                        Source)
from app.models.enums import UserRole
from app.services import contact_feedback, contact_intelligence as contacts, contributions
from tests.test_contacts import omega
from tests.test_enrichment import research, site  # noqa: F401 - the mocked-web fixture

HEADER = "ID,Company,Website,Company Phone,Country,Contact Name,Job Position,Email,Mobile,Phone,Extension," \
         "Salesperson,Last Interaction,Contact Status,Current\n"


def csv(*rows: str) -> bytes:
    return (HEADER + "\n".join(rows) + "\n").encode()


def counts(db) -> tuple:
    return tuple(db.scalar(select(func.count()).select_from(m)) for m in (Person, CompanyPerson, Email, Phone, Source))


def company(db, name, *, domain=None, phone=None, country="Lebanon") -> Company:
    c = Company(name=name, normalized_name=name.lower(), domain=domain, primary_phone=phone,
                headquarters_country=country)
    db.add(c)
    db.commit()
    return c


def test_dry_run_apply_idempotency_and_company_matching(client_for, db, site):  # noqa: F811
    agent, owner = client_for(UserRole.SALES_AGENT)
    company_id = omega(agent, site)  # Omega Foods, verified domain omegafoods.example
    research(agent, company_id)
    delta = company(db, "Delta Trading", phone="+961 1 555 000")
    db.add(CompanyAlias(company_id=delta.id, alias="Delta Group Lebanon", normalized_alias="delta group lebanon",
                        alias_type="trading"))
    company(db, "Sigma Holding")
    company(db, "Sigma Holding SAL")  # the same normalised name twice: ambiguous
    company(db, "Kappa Foods", country="France")
    db.commit()
    raw = csv(
        "od-1,Omega,www.omegafoods.example,,,Nadine Frem,Chief Financial Officer,Nadine.Frem@omegafoods.example ,"
        "03 555 666,,,,2026-09-30,confirmed,yes",
        "od-2,Delta Group Lebanon,,,,Sami Kassab,IT Manager,sami@delta.example,,01 555 777,214,,,,",
        "od-3,Another name,,+961 1 555 000,,Maya Haddad,Procurement Manager,,71 222 333,,,,,,",
        "od-4,Sigma Holding,,,,Rami Aoun,General Manager,,,,,,,,",
        "od-5,Kappa Foods,,,Lebanon,Lina Nasr,HR Manager,,,,,,,,",
        "od-6,Unknown Traders,,,,Tony Rizk,CEO,tony@unknown.example,,,,,,,",
        "od-7,Omega,www.omegafoods.example,,,Joseph Haddad,,,,,,,,,",  # no title: only a person already known
        "od-8,Omega,www.omegafoods.example,,,Nobody Known,,,,,,,,,")  # no title, unknown: never created
    before = counts(db)
    dry = contributions.ingest(db, system="ODOO_CRM", file_name="contacts.csv", raw=raw, owner_user_id=owner.id)
    assert counts(db) == before and dry["applied"] is False  # a dry run writes nothing
    assert (dry["company_exact"], dry["company_strong"], dry["company_possible"], dry["company_unmatched"]) == (
        3, 2, 1, 2)  # domain x3 | alias, phone | Sigma twice | Kappa (France), Unknown
    assert dry["rejected_no_title_unknown_person"] == 1 and dry["person_new"] == 3 and dry["person_exact"] == 1
    applied = contributions.ingest(db, system="ODOO_CRM", file_name="contacts.csv", raw=raw, owner_user_id=owner.id,
                                   apply=True)
    assert {k: v for k, v in applied.items() if k not in ("applied", "review")} == {
        k: v for k, v in dry.items() if k not in ("applied", "review")}  # the dry run said exactly what happened
    after = counts(db)
    nadine = db.scalar(select(Email).where(Email.email == "nadine.frem@omegafoods.example"))
    assert (nadine.status, nadine.provenance, nadine.last_verified_at.date().isoformat()) == (
        "confirmed", "internal_crm", "2026-09-30")  # the export said confirmed, at its own date
    sami = db.scalar(select(Phone).where(Phone.phone.like("01 555 777%")))
    assert (sami.phone_type, sami.normalized_phone) == ("office_extension", "+9611555777")
    again = contributions.ingest(db, system="ODOO_CRM", file_name="contacts.csv", raw=raw, owner_user_id=owner.id,
                                 apply=True)
    assert counts(db) == after  # idempotent: nothing duplicated
    assert again["person_exact"] == 4 and again["emails_already_known"] == 2


def test_person_matching_conflicts_phones_and_visibility(client_for, db, site):  # noqa: F811
    owner_client, owner = client_for(UserRole.SALES_AGENT)
    company_id = omega(owner_client, site)
    research(owner_client, company_id)
    rana = db.scalar(select(CompanyPerson).join(Person).where(Person.full_name == "Rana Saad"))
    contact_feedback.record_feedback(db, owner, company_id, "title_changed", company_person_id=rana.id,
                                     value="Head of Procurement")
    raw = csv(
        # the same person under a variant name, known by her work e-mail: EXACT (no duplicate person)
        "x-1,Omega,omegafoods.example,,,R. Saad,Procurement Manager,rana.saad@omegafoods.example,,,,"
        "manager@tecomsa.example,,,",
        # a different title than her colleague-confirmed one: flagged, not changed
        "x-2,Omega,omegafoods.example,,,Rana Saad,Purchasing Officer,,,,,,,,",
        # Johnny vs John: possibly the same person, another role: review, nothing attached
        "x-3,Omega,omegafoods.example,,,Karimo Aoun,Accountant,,,,,,,,",
        # no country anywhere and no international prefix: the number is kept as given, never assumed +961
        "x-4,Omega,omegafoods.example,,,Lina Khoury,Finance Director,,,555 1234,,,,,",
        # the company's main line is never the person's number
        "x-5,Omega,omegafoods.example,,,Tony Rizk,Operations Manager,,,+961 8 800 800,,,,,former")
    db.add(Email(person_id=rana.person_id, company_id=company_id, email="rana.saad@omegafoods.example",
                 status="published", provenance="public"))
    db.get(Company, company_id).headquarters_country = None
    db.commit()
    manager_client, _ = client_for(UserRole.SALES_MANAGER, email="manager@tecomsa.example")
    report = contributions.ingest(db, system="ODOO_CRM", file_name="x.csv", raw=raw, owner_user_id=owner.id,
                                  visibility="managers", apply=True)
    assert report["person_exact"] >= 1 and report["conflicts"] == 2  # both rows contradict her confirmed title
    assert db.scalar(select(func.count()).select_from(Person).where(Person.full_name.like("%Saad"))) == 1
    assert db.get(CompanyPerson, rana.id).job_title == "Head of Procurement"  # the confirmed title stands
    assert any("title conflict" in r["reason"] for r in report["review"])
    lina = db.scalar(select(Phone).where(Phone.phone == "555 1234"))
    assert lina.normalized_phone is None and report["phones_without_country_code"] == 1
    assert report["phones_company_line_skipped"] == 1
    # visibility: the owner and managers see restricted internal contacts; another salesperson does not
    other_client, _ = client_for(UserRole.SALES_AGENT, email="other@tecomsa.example")
    see = lambda client: {p["person"]["full_name"] for p in client.get(  # noqa: E731
        f"/companies/{company_id}/people").json()}
    assert "Lina Khoury" in see(manager_client) and "Lina Khoury" in see(owner_client)
    internal_only = db.scalar(select(func.count()).select_from(Phone).where(Phone.visibility != "organization"))
    assert internal_only >= 1
    assert other_client.get(f"/companies/{company_id}/people").status_code == 404  # not their company at all


def test_evidence_trail_feedback_idempotency_title_history_and_freshness(client_for, db, site):  # noqa: F811
    agent, user = client_for(UserRole.SALES_AGENT)
    company_id = omega(agent, site)
    research(agent, company_id)
    contacts.run(db, company_id)
    tony = db.scalar(select(Email).where(Email.email == "tony.rizk@omegafoods.example"))
    # a mail system's notifications by address, each applied once
    assert contact_feedback.record_email_event(db, user, "Tony.Rizk@omegafoods.example", "delivered",
                                               event_key="msg-1") == 1
    assert contact_feedback.record_email_event(db, user, "tony.rizk@omegafoods.example", "delivered",
                                               event_key="msg-1") == 0  # the same notification again
    people = {p["person"]["full_name"]: p for p in agent.get(f"/companies/{company_id}/people").json()}
    assert people["Tony Rizk"]["contacts"][0]["kind"] == "delivered_email" and not people["Tony Rizk"]["contactable"]
    contact_feedback.record_email_event(db, user, "tony.rizk@omegafoods.example", "replied", event_key="msg-2")
    trail = [e.kind for e in db.scalars(select(ContactEvidence).where(ContactEvidence.email_id == tony.id)
                                        .order_by(ContactEvidence.id))]
    assert trail == ["predicted", "delivered", "replied"]  # accumulated, never replaced
    assert db.scalar(select(func.count()).select_from(ContactFeedback)) == 2
    # a title change keeps the earlier title as history
    karim = db.scalar(select(CompanyPerson).join(Person).where(Person.full_name == "Karim Aoun"))
    db.add(CompanyPerson(company_id=company_id, person_id=karim.person_id, job_title="Systems Administrator",
                         department="it", seniority="individual_contributor", employment_status="current",
                         is_current=True, confidence=70))
    db.commit()
    contact_feedback.record_feedback(db, user, company_id, "title_changed", company_person_id=karim.id,
                                     value="Head of IT")
    db.expire_all()
    roles = {r.job_title: r.employment_status for r in db.scalars(select(CompanyPerson).where(
        CompanyPerson.person_id == karim.person_id))}
    assert roles == {"Head of IT": "current", "Systems Administrator": "former"}
    # freshness: a contact last confirmed long ago is shown as possibly outdated (never deleted)
    tony.last_verified_at = datetime.now(timezone.utc) - timedelta(days=4 * 365)
    db.commit()
    best = next(p for p in agent.get(f"/companies/{company_id}/people").json()
                if p["person"]["full_name"] == "Tony Rizk")["contacts"][0]
    assert best["kind"] == "confirmed_email" and best["stale"] is True


def test_public_and_proprietary_metrics_are_separate(client_for, db, site):  # noqa: F811
    from scripts.contact_coverage import measure

    agent, owner = client_for(UserRole.SALES_AGENT)
    company_id = omega(agent, site)
    research(agent, company_id)
    contacts.run(db, company_id)
    base = measure([company_id], public=True)["companies_contactable_strict"]  # Joseph Haddad's published address
    contributions.ingest(db, system="ODOO_CRM", file_name="c.csv", owner_user_id=owner.id, apply=True, raw=csv(
        "z-1,Omega,omegafoods.example,,,Nadine Frem,Chief Financial Officer,nadine.frem@omegafoods.example,,,,,,,"))
    tony = db.scalar(select(Email).where(Email.email == "tony.rizk@omegafoods.example"))
    contact_feedback.record_feedback(db, owner, company_id, "replied", email_id=tony.id)
    public, proprietary = measure([company_id], public=True), measure([company_id])
    assert public["companies_contactable_strict"] == base
    assert proprietary["departments"]["Finance"]["people_contactable"] ==         public["departments"]["Finance"]["people_contactable"] + 1  # Nadine is TECOMSA's knowledge only
    assert proprietary["departments"]["Operations"]["people_contactable"] == 1  # Tony's reply
    assert public["departments"]["Operations"]["people_contactable"] == 0  # publicly, a prediction
    assert proprietary["feedback"]["predicted_to_replied"] == 1.0
