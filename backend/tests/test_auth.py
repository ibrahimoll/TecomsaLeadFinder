from sqlalchemy import select

from app.models import AuditLog, UserSession
from app.models.enums import UserRole
from tests.conftest import PASSWORD, login


def test_login_success_sets_http_only_cookie(anon_client, make_user):
    user = make_user(UserRole.SALES_AGENT)

    response = login(anon_client, user.email.upper())  # email is case-insensitive

    assert response.status_code == 200
    assert response.json()["user"]["email"] == user.email
    cookie = response.headers["set-cookie"]
    assert "lf_session=" in cookie and "HttpOnly" in cookie and "samesite=lax" in cookie.lower()
    assert "password" not in response.text
    me = anon_client.get("/auth/me")
    assert me.status_code == 200 and me.json()["id"] == user.id


def test_invalid_login_is_rejected(anon_client, make_user, db):
    user = make_user()

    wrong_password = login(anon_client, user.email, "not-the-password")
    unknown_email = login(anon_client, "nobody@example.com", PASSWORD)

    assert wrong_password.status_code == 401
    assert unknown_email.status_code == 401
    assert wrong_password.json()["detail"] == unknown_email.json()["detail"]
    assert "lf_session" not in anon_client.cookies
    assert anon_client.get("/auth/me").status_code == 401
    failures = db.scalars(select(AuditLog).where(AuditLog.action == "auth.login_failed")).all()
    assert len(failures) == 2
    # Never record the attempted password
    assert all("not-the-password" not in str(f.metadata_) for f in failures)


def test_inactive_user_cannot_login(anon_client, make_user, db):
    user = make_user()
    user.is_active = False
    db.commit()
    assert login(anon_client, user.email).status_code == 401


def test_login_is_rate_limited(anon_client, make_user):
    user = make_user()
    for _ in range(10):
        assert login(anon_client, user.email, "wrong-password").status_code == 401
    assert login(anon_client, user.email).status_code == 429


def test_protected_endpoints_require_authentication(anon_client):
    for path in ("/auth/me", "/companies", "/campaigns", "/dashboard", "/users", "/audit", "/activities"):
        assert anon_client.get(path).status_code == 401, path


def test_logout_revokes_session_server_side(client_for, anon_client, db):
    client, user = client_for(UserRole.SALES_AGENT)
    copied_cookie = client.cookies.get("lf_session")
    assert anon_client.get("/auth/me", headers={"Cookie": f"lf_session={copied_cookie}"}).status_code == 200

    assert client.post("/auth/logout").status_code == 204
    assert client.get("/auth/me").status_code == 401

    # Even a copy of the old cookie no longer works.
    assert anon_client.get("/auth/me", headers={"Cookie": f"lf_session={copied_cookie}"}).status_code == 401
    session = db.scalar(select(UserSession).where(UserSession.user_id == user.id))
    assert session.revoked_at is not None


def test_login_is_audited(client_for, db):
    _, user = client_for(UserRole.SALES_AGENT)
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "auth.login"))
    assert entry is not None and entry.user_id == user.id
