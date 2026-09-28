from sqlalchemy import func, select

from app.models import AuditLog, CampaignCompany, Company, LeadActivity
from app.models.enums import UserRole

CAMPAIGN = {
    "name": "Lebanon Restaurants - Frinzo",
    "tecomsa_division": "FRINZO",
    "country": "Lebanon",
    "industry": "Restaurants",
    "target_company_count": 20,
    "target_roles": ["Marketing Manager", "Owner", "owner", " "],
    "max_lusha_credit_budget": 100,
}


def test_campaign_creation_is_draft_and_audited(client_for, db):
    agent, agent_user = client_for(UserRole.SALES_AGENT)

    response = agent.post("/campaigns", json=CAMPAIGN)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "DRAFT"
    assert body["tecomsa_division"] == "FRINZO"
    assert body["target_roles"] == ["Marketing Manager", "Owner"]
    assert body["creator"]["id"] == agent_user.id
    assert db.scalar(select(LeadActivity).where(LeadActivity.activity_type == "CAMPAIGN_CREATED"))
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "campaign.created"))
    assert audit.entity_id == str(body["id"]) and audit.user_id == agent_user.id


def test_campaign_validation(client_for):
    agent, _ = client_for(UserRole.SALES_AGENT)
    assert agent.post("/campaigns", json={**CAMPAIGN, "tecomsa_division": "OTHER"}).status_code == 422
    assert agent.post("/campaigns", json={**CAMPAIGN, "target_company_count": 0}).status_code == 422
    assert (
        agent.post("/campaigns", json={**CAMPAIGN, "company_size_min": 500, "company_size_max": 10}).status_code
        == 422
    )
    # The client cannot choose the initial status.
    assert agent.post("/campaigns", json={**CAMPAIGN, "status": "RUNNING"}).status_code == 422


def test_company_can_be_linked_to_campaign(client_for, db):
    agent, _ = client_for(UserRole.SALES_AGENT)
    campaign_id = agent.post("/campaigns", json=CAMPAIGN).json()["id"]
    company_id = agent.post("/companies", json={"name": "Linked Co"}).json()["id"]

    response = agent.post(f"/campaigns/{campaign_id}/companies/{company_id}")

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "ADDED"
    assert response.json()["company"]["odoo_status"] == "NOT_CHECKED"
    detail = agent.get(f"/campaigns/{campaign_id}").json()
    assert detail["company_count"] == 1 and detail["companies"][0]["company"]["id"] == company_id
    company = agent.get(f"/companies/{company_id}").json()
    assert company["campaigns"][0]["campaign_id"] == campaign_id

    # Adding again must not duplicate the link or the master company.
    assert agent.post(f"/campaigns/{campaign_id}/companies/{company_id}").status_code == 409
    assert db.scalar(select(func.count(CampaignCompany.id))) == 1
    assert db.scalar(select(func.count(Company.id))) == 1
    assert db.scalar(select(AuditLog).where(AuditLog.action == "campaign.company_added"))
    assert db.scalar(
        select(LeadActivity).where(LeadActivity.activity_type == "COMPANY_ADDED_TO_CAMPAIGN")
    )


def test_agents_only_see_and_edit_their_own_campaigns(client_for):
    owner, _ = client_for(UserRole.SALES_AGENT)
    other_agent, _ = client_for(UserRole.SALES_AGENT)
    manager, _ = client_for(UserRole.SALES_MANAGER)
    campaign_id = owner.post("/campaigns", json=CAMPAIGN).json()["id"]
    company_id = other_agent.post("/companies", json={"name": "Other Co"}).json()["id"]

    assert other_agent.get("/campaigns").json()["total"] == 0
    assert other_agent.get(f"/campaigns/{campaign_id}").status_code == 404
    assert other_agent.patch(f"/campaigns/{campaign_id}", json={"name": "Mine now"}).status_code == 404
    assert other_agent.post(f"/campaigns/{campaign_id}/companies/{company_id}").status_code == 404

    assert manager.get("/campaigns").json()["total"] == 1
    assert manager.patch(f"/campaigns/{campaign_id}", json={"target_company_count": 50}).status_code == 200


def test_only_draft_campaigns_are_editable(client_for):
    agent, _ = client_for(UserRole.SALES_AGENT)
    campaign_id = agent.post("/campaigns", json=CAMPAIGN).json()["id"]

    assert agent.patch(f"/campaigns/{campaign_id}", json={"status": "READY"}).json()["status"] == "READY"
    assert agent.patch(f"/campaigns/{campaign_id}", json={"name": "Renamed"}).status_code == 409
    # Execution statuses are reserved for the future pipeline.
    assert agent.patch(f"/campaigns/{campaign_id}", json={"status": "RUNNING"}).status_code == 422
    assert agent.patch(f"/campaigns/{campaign_id}", json={"status": "DRAFT"}).status_code == 200
    assert agent.patch(f"/campaigns/{campaign_id}", json={"name": "Renamed"}).status_code == 200
