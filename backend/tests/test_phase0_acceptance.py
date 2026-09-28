"""End-to-end API version of the Phase 0 acceptance workflow (spec section 27)."""

import pytest
from sqlalchemy import func, select

from app.integrations.base import IntegrationNotConfigured
from app.integrations.lusha.schemas import CompanySearchCriteria
from app.integrations.lusha.service import get_lusha_service
from app.integrations.odoo.schemas import OdooCompanyQuery
from app.integrations.odoo.service import get_odoo_service
from app.models import AuditLog, LeadActivity, LushaUsage
from app.models.enums import UserRole


def test_phase0_acceptance_workflow(client_for, db):
    agent, agent_user = client_for(UserRole.SALES_AGENT)

    # Dashboard
    assert agent.get("/dashboard").status_code == 200

    # Create campaign: Frinzo / Lebanon / Restaurants / 20 companies
    campaign = agent.post(
        "/campaigns",
        json={
            "name": "Frinzo - Lebanon Restaurants",
            "tecomsa_division": "FRINZO",
            "country": "Lebanon",
            "industry": "Restaurants",
            "target_company_count": 20,
        },
    ).json()
    assert campaign["status"] == "DRAFT"

    # Manually add a company and open its profile
    company = agent.post(
        "/companies", json={"name": "Acceptance Test Restaurant", "country": "Lebanon"}
    ).json()
    assert agent.get(f"/companies/{company['id']}").status_code == 200

    # Add a contact manually
    assert (
        agent.post("/contacts", json={"company_id": company["id"], "first_name": "Test"}).status_code == 201
    )

    # Add the company to the campaign
    assert agent.post(f"/campaigns/{campaign['id']}/companies/{company['id']}").status_code == 201

    # Odoo status: NOT CHECKED
    profile = agent.get(f"/companies/{company['id']}").json()
    assert profile["odoo_status"] == "NOT_CHECKED"

    # Lusha usage remains 0 everywhere
    assert profile["lusha_credits_used"] == 0
    assert agent.get(f"/campaigns/{campaign['id']}").json()["lusha_credits_used"] == 0
    assert agent.get("/dashboard").json()["lusha_credits_used"] == 0
    assert db.scalar(select(func.count(LushaUsage.id))) == 0

    # Activity and audit records exist
    activity_types = set(
        db.scalars(select(LeadActivity.activity_type).where(LeadActivity.user_id == agent_user.id)).all()
    )
    assert {"CAMPAIGN_CREATED", "COMPANY_CREATED", "CONTACT_ADDED", "COMPANY_ADDED_TO_CAMPAIGN"} <= activity_types
    actions = set(db.scalars(select(AuditLog.action).where(AuditLog.user_id == agent_user.id)).all())
    assert {
        "auth.login",
        "campaign.created",
        "company.created",
        "contact.created",
        "campaign.company_added",
    } <= actions
    my_activity = agent.get("/activities").json()
    assert my_activity["total"] >= 4

    # Logout, then protected resources are blocked
    assert agent.post("/auth/logout").status_code == 204
    for path in ("/dashboard", "/companies", f"/companies/{company['id']}", "/campaigns"):
        assert agent.get(path).status_code == 401


def test_integrations_are_disconnected_and_make_no_calls(db):
    odoo = get_odoo_service()
    lusha = get_lusha_service()
    assert odoo.connected is False and lusha.connected is False

    with pytest.raises(IntegrationNotConfigured):
        odoo.check_company(OdooCompanyQuery(name="X", normalized_name="x"))
    with pytest.raises(IntegrationNotConfigured):
        lusha.search_companies(CompanySearchCriteria(country="Lebanon"))
    with pytest.raises(IntegrationNotConfigured):
        lusha.reveal_email("any")

    assert db.scalar(select(func.count(LushaUsage.id))) == 0


def test_admin_can_read_audit_log(client_for):
    admin, admin_user = client_for(UserRole.ADMIN)
    response = admin.get("/audit", params={"action": "auth.login"})
    assert response.status_code == 200
    items = response.json()["items"]
    assert items and items[0]["user"]["id"] == admin_user.id and "metadata" in items[0]
