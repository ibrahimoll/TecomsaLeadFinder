"""Privacy controls: a person removed on request is deleted and never added again at that company (research or
imports); publicly researched people not seen for the retention period are deleted, TECOMSA's own and
colleague-corrected data kept."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update

from app.models import CompanyPerson, Email, Person, PersonSuppression
from app.models.enums import UserRole
from app.services import contributions, privacy
from tests.test_contacts import omega, person_id
from tests.test_contributions import SIGNATURE
from tests.test_enrichment import research, site  # noqa: F401 - the mocked-web fixture


def names(db) -> set[str]:
    db.expire_all()
    return set(db.scalars(select(Person.full_name)))


def test_removed_person_is_deleted_and_never_imported_again(client_for, db, site):  # noqa: F811
    agent, _ = client_for(UserRole.SALES_AGENT)
    manager, _ = client_for(UserRole.SALES_MANAGER)
    company_id = omega(agent, site)
    research(agent, company_id)
    tony = person_id(db, "Tony Rizk")
    url = f"/companies/{company_id}/people/{tony}/remove"
    assert agent.post(url, json={"reason": "asked by phone"}).status_code == 403  # managers / admins only
    assert manager.post(url, json={"reason": "asked by phone on 2026-10-08"}).status_code == 200
    assert "Tony Rizk" not in names(db) and "Rana Saad" in names(db)
    assert db.scalar(select(func.count()).select_from(Email).where(Email.person_id == tony)) == 0
    stored = db.scalar(select(PersonSuppression))
    assert "tony" not in stored.key_hash.lower() and len(stored.key_hash) == 64  # a hash, never the name
    report = contributions.ingest(db, system="EMAIL_SIGNATURE", file_name="sig.txt", raw=SIGNATURE.encode(),
                                  apply=True)
    assert report["suppressed_person"] == 1 and "Tony Rizk" not in names(db)
    assert privacy.is_suppressed(db, company_id, "TONY  RIZK")  # the same name key, however written
    assert manager.post(url, json={"reason": "again"}).status_code == 404


def test_retention_deletes_stale_public_people_only(client_for, db, site, monkeypatch):  # noqa: F811
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = omega(agent, site)
    research(agent, company_id)
    lina, rana = person_id(db, "Lina Khoury"), person_id(db, "Rana Saad")
    old = datetime.now(timezone.utc) - timedelta(days=800)
    db.execute(update(CompanyPerson).values(last_seen_at=old, last_verified_at=None))
    db.execute(update(CompanyPerson).where(CompanyPerson.person_id == rana).values(corrected_fields=["job_title"]))
    db.add(Email(person_id=lina, company_id=company_id, email="lina@omega-crm.example", email_type="work",
                 status="published", provenance="internal_crm"))
    db.commit()
    monkeypatch.setattr(privacy.get_settings(), "contact_retention_days", 0)
    assert privacy.purge_expired(db) == {"roles": 0, "people": 0}  # 0 = never
    monkeypatch.setattr(privacy.get_settings(), "contact_retention_days", 730)
    result = privacy.purge_expired(db)
    assert names(db) == {"Lina Khoury", "Rana Saad"}  # TECOMSA CRM contact / a colleague's correction: kept
    assert result["people"] == 3 and result["roles"] >= 3
