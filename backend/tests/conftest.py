"""Test configuration.

Tests run against a SEPARATE PostgreSQL database given by TEST_DATABASE_URL, whose
name must end in `_test`. Each test run gets its own copy (`<name>_<pid>_test`, created at the start and
dropped at the end) so that several sessions running tests at once never truncate each other's tables;
TEST_DB_SHARED=1 uses TEST_DATABASE_URL itself. The schema is built with the real Alembic migrations (empty
schema, then upgrade to head) and every table is truncated between tests.
"""

import os
import tempfile
from collections.abc import Callable, Iterator

import pytest
from sqlalchemy.engine import make_url

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    pytest.exit("TEST_DATABASE_URL is not set - refusing to run tests.", returncode=2)
if not (make_url(TEST_DATABASE_URL).database or "").endswith("_test"):
    pytest.exit("TEST_DATABASE_URL must point to a database whose name ends in '_test'.", returncode=2)

_SHARED_URL = make_url(TEST_DATABASE_URL)
_OWN_DATABASE = os.environ.get("TEST_DB_SHARED") != "1"
if _OWN_DATABASE:
    TEST_DATABASE_URL = _SHARED_URL.set(database=f"{_SHARED_URL.database[:-5]}_{os.getpid()}_test").render_as_string(
        hide_password=False)

# Must be set before any `app` module is imported.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["ENVIRONMENT"] = "test"
os.environ["COOKIE_SECURE"] = "false"
os.environ["JWT_SECRET"] = "test-jwt-secret-" + "x" * 32
os.environ["APP_SECRET"] = "test-app-secret-" + "x" * 32
os.environ["CORS_EXTRA_ORIGINS"] = ""
os.environ["FRONTEND_URL"] = "http://localhost:3000"
# Discovery is hermetic: tests run jobs explicitly (jobs.run_next) against fake connectors and a mocked web.
os.environ["DISCOVERY_WORKER_ENABLED"] = "false"
os.environ["DISCOVERY_CACHE_DIR"] = tempfile.mkdtemp(prefix="leadfinder-test-discovery-")
os.environ["WEBSITE_MIN_INTERVAL_SECONDS"] = "0"
os.environ["COMMONCRAWL_MIN_INTERVAL_SECONDS"] = "0"

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.rate_limit import login_limiter  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, User  # noqa: E402
from app.models.enums import UserRole  # noqa: E402
from app.schemas.user import UserCreate  # noqa: E402
from app.services import user_service  # noqa: E402

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASSWORD = "Correct-Horse-Battery-9"


def alembic_config() -> Config:
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "migrations"))
    cfg.attributes["database_url"] = TEST_DATABASE_URL
    cfg.attributes["configure_logger"] = False
    return cfg


def reset_schema() -> None:
    """Empty the test database completely (0014 cannot be downgraded, so `downgrade base` is not an option)."""
    engine.dispose()
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))


def _server_admin(sql: str) -> None:
    """CREATE / DROP DATABASE on the test server (outside a transaction), through its `postgres` database."""
    from sqlalchemy import create_engine

    admin = create_engine(_SHARED_URL.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(sql))
    admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    name = make_url(TEST_DATABASE_URL).database
    if _OWN_DATABASE:
        _server_admin(f'DROP DATABASE IF EXISTS "{name}"')  # a leftover of a crashed run with the same pid
        _server_admin(f'CREATE DATABASE "{name}"')
    reset_schema()
    command.upgrade(alembic_config(), "head")  # the real migrations, from an empty database
    yield
    engine.dispose()
    if _OWN_DATABASE:
        _server_admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture(autouse=True)
def clean_tables() -> Iterator[None]:
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    login_limiter.reset()
    yield


@pytest.fixture(autouse=True)
def public_apis(monkeypatch):
    """Public APIs (Wikidata, Common Crawl, JSON listings) are never called for real in tests: by default they know
    nothing; a test sets `public_apis.routes[(host, path)] = handler(request) -> httpx.Response`."""
    import httpx

    from app.services.people.external.lebanon import commoncrawl, pack

    state = type("PublicApis", (), {})()
    state.routes, state.requests = {}, []

    def handler(request: httpx.Request) -> httpx.Response:
        state.requests.append(f"{request.url.host}{request.url.path}")
        route = state.routes.get((request.url.host, request.url.path))
        if route is not None:
            return route(request)
        if request.url.host == "www.wikidata.org":
            return httpx.Response(200, json={"search": [], "entities": {}})
        if request.url.path == "/collinfo.json":
            return httpx.Response(200, json=[])
        if request.url.path == "/cc-index/collections/index.html":  # Common Crawl's static index: no crawl listed
            return httpx.Response(200, text="")
        return httpx.Response(404, text="")

    monkeypatch.setattr(pack, "api_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(commoncrawl, "_last", [0.0])
    monkeypatch.setattr(commoncrawl, "_down_until", [0.0])  # the archive outage breaker: per test
    from app.services import contact_intelligence

    # e-mail domains: a mail server for every domain unless a test says otherwise (no real DNS in tests)
    monkeypatch.setattr(contact_intelligence, "mx_hosts", lambda domain: [f"mx.{domain}"])
    from app.services.people.external.lebanon import wikidata

    monkeypatch.setattr(wikidata, "MIN_INTERVAL", 0)
    from app.core.config import get_settings

    for key in ("searxng_url", "langsearch_api_key", "tavily_api_key", "brave_search_api_key"):
        monkeypatch.setattr(get_settings(), key, None)  # no real web search engine, unless a test installs one
    return state


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def make_user(db) -> Callable[..., User]:
    counter = {"n": 0}

    def _make(role: UserRole = UserRole.SALES_AGENT, email: str | None = None, **kw) -> User:
        counter["n"] += 1
        email = email or f"{role.value.lower()}{counter['n']}@example.com"
        return user_service.create_user(
            db,
            None,
            UserCreate(name=kw.get("name", f"Test {role.value}"), email=email, password=PASSWORD, role=role),
        )

    return _make


def login(client: TestClient, email: str, password: str = PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


@pytest.fixture
def client_for(make_user) -> Callable[..., tuple[TestClient, User]]:
    """Returns an authenticated TestClient (each with its own cookie jar) plus its user."""
    clients: list[TestClient] = []

    def _client(role: UserRole = UserRole.SALES_AGENT, **kw) -> tuple[TestClient, User]:
        user = make_user(role, **kw)
        client = TestClient(app)
        clients.append(client)
        response = login(client, user.email)
        assert response.status_code == 200, response.text
        return client, user

    yield _client
    for c in clients:
        c.close()


@pytest.fixture
def anon_client() -> Iterator[TestClient]:
    with TestClient(app) as client:
        yield client
