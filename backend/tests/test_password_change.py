"""Changing one's own password: the current one required (wrong guesses rate-limited), the other sessions signed
out while this one stays, the new password works and the old one no longer does."""

from fastapi.testclient import TestClient

from app.main import app
from app.models.enums import UserRole
from tests.conftest import PASSWORD, login


def test_change_own_password(client_for, make_user):
    me, user = client_for(UserRole.SALES_AGENT)
    other = TestClient(app)
    assert login(other, user.email).status_code == 200  # a second session (another browser)
    bad = me.post("/auth/password", json={"current_password": "wrong-password", "new_password": "a-new-long-pass"})
    assert bad.status_code == 422
    ok = me.post("/auth/password", json={"current_password": PASSWORD, "new_password": "a-new-long-pass"})
    assert ok.status_code == 204, ok.text
    assert me.get("/auth/me").status_code == 200  # this session stays
    assert other.get("/auth/me").status_code == 401  # the other one is signed out
    fresh = TestClient(app)
    assert fresh.post("/auth/login", json={"email": user.email, "password": "a-new-long-pass"}).status_code == 200
    assert fresh.post("/auth/login", json={"email": user.email, "password": PASSWORD}).status_code == 401
