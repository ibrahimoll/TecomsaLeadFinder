from sqlalchemy import select

from app.models import AuditLog, LeadActivity, OdooMatch
from app.models.enums import UserRole

COMPANY = {
    "name": "Café Beirut S.A.L.",
    "website": "https://WWW.CafeBeirut.example.com/menu",
    "country": "Lebanon",
    "city": "Beirut",
    "industry": "Restaurants",
    "main_phone": "+961 1 234 567",
    "main_email": "Info@CafeBeirut.example.com",
    "company_size": "11-50",
    "description": "Test record",
}


def test_company_creation_normalizes_and_records_events(client_for, db):
    agent, agent_user = client_for(UserRole.SALES_AGENT)

    response = agent.post("/companies", json=COMPANY)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["normalized_name"] == "cafe beirut"
    assert body["domain"] == "cafebeirut.example.com"
    assert body["main_phone_normalized"] == "+9611234567"
    assert body["main_email"] == "info@cafebeirut.example.com"
    assert body["creator"]["id"] == agent_user.id

    activity = db.scalar(select(LeadActivity).where(LeadActivity.company_id == body["id"]))
    assert activity.activity_type == "COMPANY_CREATED"
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "company.created"))
    assert audit.entity_id == str(body["id"]) and audit.user_id == agent_user.id


def test_odoo_status_defaults_to_not_checked(client_for, db):
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = agent.post("/companies", json={"name": "Acme Trading"}).json()["id"]

    matches = db.scalars(select(OdooMatch).where(OdooMatch.company_id == company_id)).all()
    assert len(matches) == 1
    assert matches[0].match_status == "NOT_CHECKED"
    assert matches[0].checked_at is None and matches[0].odoo_partner_id is None

    detail = agent.get(f"/companies/{company_id}").json()
    assert detail["odoo_status"] == "NOT_CHECKED"
    assert detail["odoo_match"]["match_status"] == "NOT_CHECKED"
    listing = agent.get("/companies").json()
    assert listing["items"][0]["odoo_status"] == "NOT_CHECKED"


def test_company_name_is_not_unique(client_for):
    agent, _ = client_for(UserRole.SALES_AGENT)
    assert agent.post("/companies", json={"name": "Same Name"}).status_code == 201
    assert agent.post("/companies", json={"name": "Same Name"}).status_code == 201


def test_invalid_company_input_is_rejected(client_for):
    agent, _ = client_for(UserRole.SALES_AGENT)
    assert agent.post("/companies", json={"name": ""}).status_code == 422
    assert agent.post("/companies", json={"name": "X", "website": "not a url"}).status_code == 422
    assert agent.post("/companies", json={"name": "X", "main_email": "nope"}).status_code == 422
    assert agent.post("/companies", json={"name": "X", "unexpected": 1}).status_code == 422


def test_company_search_and_pagination(client_for):
    agent, _ = client_for(UserRole.SALES_AGENT)
    for name in ("Alpha Foods", "Beta Steel", "Alpha Motors"):
        agent.post("/companies", json={"name": name})

    result = agent.get("/companies", params={"q": "alpha", "page_size": 1}).json()
    assert result["total"] == 2 and len(result["items"]) == 1 and result["page_size"] == 1


def test_agent_cannot_edit_company_created_by_someone_else(client_for, db):
    owner, _ = client_for(UserRole.SALES_AGENT)
    other_agent, _ = client_for(UserRole.SALES_AGENT)
    manager, _ = client_for(UserRole.SALES_MANAGER)
    company_id = owner.post("/companies", json={"name": "Owned Co"}).json()["id"]

    # Any user may view the shared company database...
    assert other_agent.get(f"/companies/{company_id}").status_code == 200
    # ...but agents may only edit their own records.
    assert other_agent.patch(f"/companies/{company_id}", json={"name": "Hijacked"}).status_code == 403
    assert owner.patch(f"/companies/{company_id}", json={"city": "Tripoli"}).status_code == 200
    assert manager.patch(f"/companies/{company_id}", json={"city": "Byblos"}).status_code == 200

    edits = db.scalars(select(AuditLog).where(AuditLog.action == "company.updated")).all()
    assert [e.metadata_["changes"]["city"]["to"] for e in edits] == ["Tripoli", "Byblos"]


def test_contacts_are_manual_and_belong_to_company(client_for, db):
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = agent.post("/companies", json={"name": "Contact Co"}).json()["id"]

    response = agent.post(
        "/contacts",
        json={"company_id": company_id, "first_name": "Rana", "last_name": "Haddad", "job_title": "CEO"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["source"] == "MANUAL"
    detail = agent.get(f"/companies/{company_id}").json()
    assert [c["full_name"] for c in detail["contacts"]] == ["Rana Haddad"]
    assert agent.post("/contacts", json={"company_id": 99999, "first_name": "X"}).status_code == 404
    assert db.scalar(select(AuditLog).where(AuditLog.action == "contact.created")) is not None


def test_company_note_creates_activity(client_for):
    agent, _ = client_for(UserRole.SALES_AGENT)
    company_id = agent.post("/companies", json={"name": "Note Co"}).json()["id"]

    assert agent.post(f"/companies/{company_id}/notes", json={"notes": "Called reception"}).status_code == 204
    activity = agent.get("/activities", params={"company_id": company_id}).json()["items"]
    assert activity[0]["activity_type"] == "NOTE_ADDED" and activity[0]["notes"] == "Called reception"
