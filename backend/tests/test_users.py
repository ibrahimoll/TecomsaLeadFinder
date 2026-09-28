from sqlalchemy import select

from app.models import AuditLog, User
from app.models.enums import UserRole
from tests.conftest import login

NEW_USER = {
    "name": "New Agent",
    "email": "New.Agent@Example.com",
    "password": "A-Strong-Password-1",
    "role": "SALES_AGENT",
    "odoo_user_id": 42,
}


def test_admin_can_create_user(client_for, anon_client, db):
    admin, admin_user = client_for(UserRole.ADMIN)

    response = admin.post("/users", json=NEW_USER)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == "new.agent@example.com"
    assert body["odoo_user_id"] == 42
    assert "password" not in body and "password_hash" not in body
    stored = db.scalar(select(User).where(User.email == "new.agent@example.com"))
    assert stored.password_hash != NEW_USER["password"]
    audit = db.scalar(
        select(AuditLog).where(AuditLog.action == "user.created", AuditLog.entity_id == str(body["id"]))
    )
    assert audit.user_id == admin_user.id
    assert "A-Strong-Password-1" not in str(audit.metadata_)
    assert login(anon_client, "new.agent@example.com", NEW_USER["password"]).status_code == 200


def test_duplicate_email_is_rejected(client_for):
    admin, _ = client_for(UserRole.ADMIN)
    assert admin.post("/users", json=NEW_USER).status_code == 201
    assert admin.post("/users", json=NEW_USER).status_code == 409


def test_sales_agent_cannot_access_admin_routes(client_for, make_user):
    agent, _ = client_for(UserRole.SALES_AGENT)
    other = make_user(UserRole.SALES_AGENT)

    assert agent.get("/users").status_code == 403
    assert agent.post("/users", json=NEW_USER).status_code == 403
    assert agent.patch(f"/users/{other.id}", json={"is_active": False}).status_code == 403
    assert agent.get("/audit").status_code == 403
    assert agent.get("/settings/status").status_code == 403


def test_sales_manager_can_list_but_not_manage_users(client_for):
    manager, _ = client_for(UserRole.SALES_MANAGER)
    assert manager.get("/users").status_code == 200
    assert manager.post("/users", json=NEW_USER).status_code == 403
    assert manager.get("/audit").status_code == 403


def test_deactivation_blocks_access_immediately_and_is_audited(client_for, db):
    admin, _ = client_for(UserRole.ADMIN)
    agent, agent_user = client_for(UserRole.SALES_AGENT)
    assert agent.get("/auth/me").status_code == 200

    response = admin.patch(f"/users/{agent_user.id}", json={"is_active": False})

    assert response.status_code == 200 and response.json()["is_active"] is False
    assert agent.get("/auth/me").status_code == 401
    assert db.scalar(select(AuditLog).where(AuditLog.action == "user.deactivated")) is not None


def test_admin_cannot_deactivate_self(client_for):
    admin, admin_user = client_for(UserRole.ADMIN)
    assert admin.patch(f"/users/{admin_user.id}", json={"is_active": False}).status_code == 422
