"""The real migration path: a V1 database (0013) with users is upgraded to V2 without losing them,
and the migrated schema is exactly what the ORM models describe (what `alembic check` verifies)."""

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text

from app.db.session import engine
from app.models import Base
from tests.conftest import alembic_config, reset_schema

V2_TABLES = {"companies", "company_locations", "company_relationships", "company_aliases", "company_lookups", "company_domains", "company_email_patterns", "contact_evidence", "person_suppressions", "contact_feedback", "company_gap_reasons",
             "source_lookups", "people", "company_people", "emails",
             "phones", "sources", "evidence",
             "lead_searches", "lead_search_results", "research_runs", "opportunity_analysis",
             "company_status_history", "integrations", "company_identifiers", "possible_duplicates",
             "discovery_suppressions", "company_signals", "company_products_services", "company_web_pages",
             "possible_duplicate_people", "external_documents", "external_search_cache"}


def test_v1_database_upgrades_keeping_users_sessions_and_audit_log():
    cfg = alembic_config()
    reset_schema()
    command.upgrade(cfg, "0013")
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users (id, name, email, password_hash, role) "
                          "VALUES (7, 'Kept Admin', 'kept@example.com', 'hash', 'ADMIN')"))
        conn.execute(text("INSERT INTO user_sessions (id, user_id, expires_at) VALUES ('s1', 7, now() + interval '1 h')"))
        conn.execute(text("INSERT INTO audit_logs (user_id, action) VALUES (7, 'auth.login')"))
        conn.execute(text("INSERT INTO companies (name, normalized_name, country, source) "
                          "VALUES ('Old Co', 'old co', 'Lebanon', 'MANUAL')"))

    command.upgrade(cfg, "head")

    with engine.connect() as conn:
        assert conn.execute(text("SELECT email FROM users WHERE id = 7")).scalar() == "kept@example.com"
        assert conn.execute(text("SELECT count(*) FROM user_sessions")).scalar() == 1
        assert conn.execute(text("SELECT count(*) FROM audit_logs")).scalar() == 1
        assert conn.execute(text("SELECT count(*) FROM companies")).scalar() == 0  # business data starts at zero
    tables = set(inspect(engine).get_table_names())
    assert V2_TABLES <= tables
    assert not tables & {"crm_leads", "campaigns", "decision_makers", "sales_leads", "discovery_runs", "salespeople"}
    assert tables == V2_TABLES | {"users", "user_sessions", "audit_logs", "alembic_version"}

    with pytest.raises(RuntimeError, match="irreversible"):
        command.downgrade(cfg, "0013")


def test_migrated_schema_matches_the_models():
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    assert diff == []
