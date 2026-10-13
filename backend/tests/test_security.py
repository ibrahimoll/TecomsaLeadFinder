"""Security regression tests (authentication, sessions, CSRF, authorization, mass assignment,
injection, secrets, production configuration, audit)."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select

from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.main import _refuse_demo_accounts, app
from app.models import AuditLog, Company, CompanyStatusHistory, Integration, User, UserSession
from app.models.enums import UserRole
from tests.conftest import PASSWORD, login

APP_ORIGIN = "http://localhost:3000"


def company(client, name: str, **fields) -> int:
    response = client.post("/companies", json={"name": name, **fields})
    assert response.status_code == 201, response.text
    return response.json()["id"]


# ---- 1-6: authentication and sessions ----------------------------------------------------------------


OPEN = {"/health", "/auth/login", "/auth/logout", "/docs", "/openapi.json", "/docs/oauth2-redirect", "/redoc"}


def test_every_api_route_requires_a_session(anon_client):
    checked = 0
    for path, operations in app.openapi()["paths"].items():  # every documented endpoint
        if path in OPEN:
            continue
        url = "/".join("1" if part.startswith("{") else part for part in path.split("/"))
        for method in (m.upper() for m in operations):
            response = anon_client.request(method, url, json={})
            assert response.status_code == 401, (method, path, response.status_code)
            checked += 1
    assert checked >= 15


def test_inactive_expired_and_logged_out_sessions_are_refused(make_user, db):
    user = make_user(UserRole.SALES_AGENT)
    a, b = TestClient(app), TestClient(app)
    assert login(a, user.email).status_code == 200
    cookie = a.cookies.get(get_settings().cookie_name)
    b.cookies.set(get_settings().cookie_name, cookie)
    assert b.get("/auth/me").status_code == 200  # a copied cookie works only while the session is valid
    assert a.post("/auth/logout", headers={"Origin": APP_ORIGIN}).status_code == 204
    assert b.get("/auth/me").status_code == 401  # revoked server-side, not just deleted in the browser

    assert login(a, user.email).status_code == 200
    db.execute(UserSession.__table__.update().values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
    db.commit()
    assert a.get("/auth/me").status_code == 401  # expired

    assert login(a, user.email).status_code == 200
    db.get(User, user.id).is_active = False
    db.commit()
    assert a.get("/auth/me").status_code == 401  # deactivated: existing sessions stop working
    assert login(a, user.email).status_code == 401  # and no new ones

    for forged in ("garbage", "eyJhbGciOiJub25lIn0.eyJzdWIiOiIxIiwic2lkIjoieCJ9.", cookie[:-4] + "AAAA"):
        c = TestClient(app)
        c.cookies.set(get_settings().cookie_name, forged)
        assert c.get("/auth/me").status_code == 401


def test_login_rate_limit_and_no_user_enumeration(anon_client, make_user):
    user = make_user(UserRole.SALES_AGENT)
    unknown = anon_client.post("/auth/login", json={"email": "nobody@example.com", "password": "Wrong-password-1"})
    wrong = anon_client.post("/auth/login", json={"email": user.email, "password": "Wrong-password-1"})
    assert unknown.status_code == wrong.status_code == 401 and unknown.json() == wrong.json()
    for _ in range(get_settings().login_rate_limit_attempts - 1):
        anon_client.post("/auth/login", json={"email": user.email, "password": "Wrong-password-1"})
    limited = anon_client.post("/auth/login", json={"email": user.email, "password": PASSWORD})
    assert limited.status_code == 429  # even the right password, until the window passes


def test_session_cookie_flags(anon_client, make_user, monkeypatch):
    user = make_user(UserRole.SALES_AGENT)
    cookie = login(anon_client, user.email).headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie and "max-age=" in cookie
    monkeypatch.setattr(get_settings(), "cookie_secure", True)
    assert "secure" in login(TestClient(app), user.email).headers["set-cookie"].lower()


# ---- CSRF, CORS, body size, headers --------------------------------------------------------------------


def test_cross_site_state_changes_are_refused(client_for):
    agent, _ = client_for(UserRole.SALES_AGENT)
    body = {"name": "Csrf Co", "headquarters_country": "Lebanon"}
    assert agent.post("/companies", json=body, headers={"Origin": "https://evil.example"}).status_code == 403
    assert agent.post("/companies", json=body, headers={"Origin": "null"}).status_code == 403
    assert agent.post("/companies", json=body, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert agent.post("/lead-searches", json={"country": "Lebanon"},
                      headers={"Origin": "https://evil.example"}).status_code == 403
    assert agent.post("/auth/logout", headers={"Origin": "https://evil.example"}).status_code == 403
    assert agent.get("/auth/me", headers={"Origin": "https://evil.example"}).status_code == 200  # reads: CORS
    assert agent.post("/companies", json=body, headers={"Origin": APP_ORIGIN, "Sec-Fetch-Site": "same-origin"}
                      ).status_code == 201
    with SessionLocal() as s:
        assert s.scalar(select(func.count(Company.id))) == 1
    # Without a session cookie there is nothing to ride on (login keeps working).
    anon = TestClient(app)
    assert anon.post("/auth/login", json={"email": "x@example.com", "password": "y"},
                     headers={"Origin": "https://evil.example"}).status_code == 401


def test_cors_does_not_trust_other_origins(anon_client):
    preflight = anon_client.options("/companies", headers={"Origin": "https://evil.example",
                                                           "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in preflight.headers
    ok = anon_client.options("/companies", headers={"Origin": APP_ORIGIN, "Access-Control-Request-Method": "POST"})
    assert ok.headers["access-control-allow-origin"] == APP_ORIGIN != "*"


def test_oversized_bodies_are_refused_before_parsing(anon_client, client_for):
    big = b"x" * (1024 * 1024 + 10)
    assert anon_client.post("/auth/login", content=big, headers={"content-type": "application/json"}).status_code == 413
    agent, _ = client_for(UserRole.SALES_AGENT)
    assert agent.post("/companies", content=big, headers={"content-type": "application/json"}).status_code == 413


def test_security_headers_and_errors_without_internals(client_for, monkeypatch):
    agent, _ = client_for(UserRole.SALES_AGENT)
    response = agent.get("/auth/me")
    for header, value in {"x-content-type-options": "nosniff", "x-frame-options": "DENY",
                          "cache-control": "no-store", "referrer-policy": "no-referrer"}.items():
        assert response.headers[header] == value
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]

    from app.services import company_service

    def boom(*_args, **_kw):
        raise RuntimeError("psycopg.OperationalError at /app/app/services/x.py password=hunter2")

    monkeypatch.setattr(company_service, "list_companies", boom)
    with TestClient(app, raise_server_exceptions=False) as c:
        login(c, agent.get("/auth/me").json()["email"])
        failed = c.get("/companies")
    assert failed.status_code == 500 and failed.json() == {"detail": "Internal server error"}


# ---- 7-17: authorization, escalation, mass assignment --------------------------------------------------


def test_agent_cannot_escalate_or_delete(client_for):
    agent, user = client_for(UserRole.SALES_AGENT)
    manager, _ = client_for(UserRole.SALES_MANAGER)
    cid = company(agent, "Kept Co")
    for method, path in (("GET", "/users"), ("POST", "/users"), ("PATCH", f"/users/{user.id}"), ("GET", "/audit"),
                         ("GET", "/settings/status"), ("DELETE", f"/companies/{cid}")):
        assert agent.request(method, path, json={"role": "ADMIN"}).status_code == 403, (method, path)
    for method, path in (("POST", "/users"), ("GET", "/audit"), ("GET", "/settings/status")):
        assert manager.request(method, path, json={}).status_code == 403, ("manager", method, path)
    assert agent.get("/auth/me").json()["role"] == "SALES_AGENT"
    assert agent.get(f"/companies/{cid}").status_code == 200


@pytest.mark.parametrize("field,value", [("status", "opportunity"), ("normalized_name", "x"), ("created_by_user_id", 1),
                                         ("last_verified_at", "2026-01-01T00:00:00Z"), ("id", 99), ("role", "ADMIN")])
def test_mass_assignment_is_rejected(client_for, field, value):
    agent, _ = client_for(UserRole.SALES_AGENT)
    cid = company(agent, "Plain Co")
    assert agent.post("/companies", json={"name": "Other Co", field: value}).status_code == 422
    assert agent.patch(f"/companies/{cid}", json={field: value}).status_code == 422


@pytest.mark.parametrize("field,value", [("user_id", 1), ("status", "completed"), ("companies_found", 99),
                                         ("started_at", "2026-01-01T00:00:00Z")])
def test_lead_search_owner_and_state_come_from_the_server(client_for, field, value):
    agent, user = client_for(UserRole.SALES_AGENT)
    assert agent.post("/lead-searches", json={"country": "Lebanon", field: value}).status_code == 422
    assert agent.post("/lead-searches", json={"country": "Lebanon"}).json()["user_id"] == user.id


# ---- 18-20: injection and XSS ---------------------------------------------------------------------------


SQLI = ["' OR 1=1 --", "x'; DROP TABLE companies; --", "%' UNION SELECT password_hash FROM users --", "\\'; --"]
XSS = '<script>alert(1)</script><img src=x onerror=alert(1)>'


def test_sql_injection_payloads_are_data(client_for):
    agent, _ = client_for(UserRole.SALES_AGENT)
    manager, _ = client_for(UserRole.SALES_MANAGER)
    company(agent, "Visible Co")
    for payload in SQLI:
        for client, path, params in ((agent, "/companies", {"q": payload}), (agent, "/companies", {"industry": payload}),
                                     (agent, "/companies", {"country": payload, "city": payload}),
                                     (manager, "/users", {"q": payload})):
            response = client.get(path, params=params)
            assert response.status_code in (200, 422), (path, response.text)
            if response.status_code == 200:
                assert response.json()["total"] == 0, (path, payload)
        assert agent.get("/companies", params={"status": payload}).status_code == 422
    stored = company(agent, SQLI[1])
    assert agent.get(f"/companies/{stored}").json()["company"]["name"] == SQLI[1]
    with SessionLocal() as s:
        assert s.scalar(select(func.count(Company.id))) == 2  # the table is still there


def test_stored_and_reflected_markup_is_returned_as_json_text(client_for):
    agent, _ = client_for(UserRole.SALES_AGENT)
    cid = company(agent, XSS, description=XSS)
    agent.patch(f"/companies/{cid}/status", json={"status": "contacted", "reason": XSS})
    detail = agent.get(f"/companies/{cid}")
    assert detail.headers["content-type"].startswith("application/json")
    assert detail.json()["company"]["name"] == XSS  # stored verbatim; React renders it as text
    reflected = agent.get(f"/companies/{XSS}")
    assert reflected.headers["content-type"].startswith("application/json") and "<script>" not in reflected.text


def test_dangerous_url_schemes_never_stored_as_links(client_for):
    agent, _ = client_for(UserRole.SALES_AGENT)
    for url in ("javascript:alert(1)", "data:text/html,<script>alert(1)</script>", "vbscript:msgbox(1)",
                "javascript://example.com/%0aalert(1)", "file:///etc/passwd"):
        response = agent.post("/companies", json={"name": f"Scheme {url[:5]}", "website": url})
        if response.status_code == 201:
            assert response.json()["website"].startswith(("https://", "http://"))
            assert "javascript:" not in response.json()["website"].split("://", 1)[0]
        for field in ("linkedin_url", "instagram_url", "facebook_url"):
            assert agent.post("/companies", json={"name": "Social", field: url}).status_code == 422, (field, url)


# ---- 30-37: secrets ---------------------------------------------------------------------------------------


def test_secrets_never_leave_the_server(client_for, db):
    admin, _ = client_for(UserRole.ADMIN)
    agent, _ = client_for(UserRole.SALES_AGENT)
    cid = company(agent, "Leak Check Co")
    db.add(Integration(integration_type="odoo", display_name="Odoo", configuration={"database": "prod"}))
    db.commit()
    pages = [admin.get(p).text for p in ("/settings/status", "/auth/me", "/audit", "/users")]
    pages += [agent.get(p).text for p in ("/auth/me", "/companies", f"/companies/{cid}")]
    assert "Odoo" in pages[0]
    for text in pages:
        for secret in (get_settings().jwt_secret, get_settings().app_secret, "password_hash", "$argon2"):
            assert secret not in text


# ---- 39-41: production configuration ----------------------------------------------------------------------


GOOD = dict(environment="production", app_secret="a" * 40, jwt_secret="b" * 40,
            database_url="postgresql+psycopg://lf:Very-Long-Db-Password-2026@db:5432/lf",
            frontend_url="https://leadfinder.tecomsa.me", cors_extra_origins="", cookie_secure=None)


@pytest.mark.parametrize("change,problem", [
    ({"jwt_secret": "short"}, "JWT_SECRET"),
    ({"app_secret": "dev-insecure-app-secret-do-not-use-in-production"}, "APP_SECRET"),
    ({"jwt_secret": "a" * 40}, "different"),
    ({"database_url": "postgresql+psycopg://leadfinder:change-me-local-dev-password@db/lf"}, "database password"),
    ({"database_url": "postgresql+psycopg://lf:leadfinder@db/lf"}, "database password"),
    ({"cookie_secure": False}, "COOKIE_SECURE"),
    ({"frontend_url": "http://leadfinder.tecomsa.me"}, "https"),
    ({"cors_extra_origins": "*"}, "https"),
    ({"cors_extra_origins": "http://localhost:3000"}, "https"),
    ({"jwt_algorithm": "none"}, "JWT_ALGORITHM"),
])
def test_production_refuses_unsafe_configuration(change, problem):
    Settings(_env_file=None, **GOOD)  # the safe baseline starts
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None, **{**GOOD, **change})
    assert problem in str(exc.value)
    assert Settings(_env_file=None, **GOOD).secure_cookies is True  # Secure cookies by default in production


def test_production_refuses_active_demo_accounts(make_user):
    _refuse_demo_accounts()  # none: fine
    make_user(UserRole.ADMIN, email="demo.admin@example.com")
    with pytest.raises(RuntimeError, match="demo"):
        _refuse_demo_accounts()


# ---- 43-44: audit trail ------------------------------------------------------------------------------------


def test_audit_log_is_read_only_and_actor_comes_from_the_session(client_for, make_user):
    admin, admin_user = client_for(UserRole.ADMIN)
    agent, agent_user = client_for(UserRole.SALES_AGENT)
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert admin.request(method, "/audit", json={}).status_code in (403, 405)
        assert admin.request(method, "/audit/1", json={}).status_code in (403, 404, 405)
    cid = company(agent, "Audited Co")
    forged = agent.patch(f"/companies/{cid}/status", json={"status": "contacted", "changed_by_user_id": admin_user.id,
                                                           "created_at": "2001-01-01T00:00:00Z"})
    assert forged.status_code == 422
    agent.patch(f"/companies/{cid}/status", json={"status": "contacted"})
    with SessionLocal() as s:
        entry = s.scalar(select(AuditLog).where(AuditLog.action == "company.status_changed"))
        assert entry.user_id == agent_user.id and entry.created_at > datetime.now(timezone.utc) - timedelta(minutes=5)
        assert s.scalar(select(CompanyStatusHistory.changed_by_user_id)) == agent_user.id
        login_entries = s.scalars(select(AuditLog).where(AuditLog.action == "auth.login")).all()
        assert all("password" not in str(e.metadata_ or {}).lower() for e in login_entries)


def test_a_token_issued_a_moment_in_the_future_is_accepted():
    """The clock stepping back a moment (WSL / NTP) right after a login must not log the person out."""
    from datetime import datetime, timedelta, timezone

    import jwt

    from app.core.config import get_settings
    from app.core.security import decode_session_token

    s = get_settings()
    now = datetime.now(timezone.utc)
    token = jwt.encode({"sub": "1", "sid": "x", "iat": now + timedelta(seconds=5), "exp": now + timedelta(hours=1)},
                       s.jwt_secret, algorithm=s.jwt_algorithm)
    assert decode_session_token(token)["sid"] == "x"
    expired = jwt.encode({"sub": "1", "sid": "x", "exp": now - timedelta(seconds=5)}, s.jwt_secret,
                         algorithm=s.jwt_algorithm)
    assert decode_session_token(expired) is None  # the expiry still counts
