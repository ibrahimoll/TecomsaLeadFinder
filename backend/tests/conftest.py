"""Test configuration.

Tests run against a SEPARATE PostgreSQL database given by TEST_DATABASE_URL, whose
name must end in `_test`. The schema is built with the real Alembic migrations
(downgrade to base, then upgrade to head) and every table is truncated between tests.
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

# Must be set before any `app` module is imported.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["ENVIRONMENT"] = "test"
os.environ["COOKIE_SECURE"] = "false"
os.environ["JWT_SECRET"] = "test-jwt-secret-" + "x" * 32
os.environ["APP_SECRET"] = "test-app-secret-" + "x" * 32
os.environ["IMPORT_STORAGE_DIR"] = tempfile.mkdtemp(prefix="leadfinder-test-imports-")
os.environ["MANAGERS_CAN_IMPORT"] = "false"

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


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "migrations"))
    cfg.attributes["database_url"] = TEST_DATABASE_URL
    cfg.attributes["configure_logger"] = False
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_tables() -> Iterator[None]:
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    login_limiter.reset()
    yield


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

    def _client(role: UserRole = UserRole.SALES_AGENT) -> tuple[TestClient, User]:
        user = make_user(role)
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
