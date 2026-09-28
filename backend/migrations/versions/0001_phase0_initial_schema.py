"""Phase 0 initial schema

Creates users, user_sessions, companies, contacts, campaigns, campaign_companies,
odoo_matches, lusha_usage, lead_activities and audit_logs.

Revision ID: 0001
Revises:
Create Date: 2026-09-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Enumerations are frozen here on purpose: later changes belong in new migrations.
USER_ROLES = ("ADMIN", "SALES_MANAGER", "SALES_AGENT")
DIVISIONS = ("FRINZO", "ODOO", "IT")
CAMPAIGN_STATUSES = ("DRAFT", "READY", "RUNNING", "COMPLETED", "FAILED", "CANCELLED")
CAMPAIGN_COMPANY_STATUSES = ("ADDED", "REVIEW", "REMOVED")
QUALIFICATION_STATUSES = ("PENDING", "QUALIFIED", "DISQUALIFIED")
ODOO_MATCH_STATUSES = (
    "NOT_CHECKED",
    "NEW",
    "EXISTING_CONTACT",
    "EXISTING_CUSTOMER",
    "ACTIVE_OPPORTUNITY",
    "PREVIOUSLY_CONTACTED",
    "POSSIBLE_DUPLICATE",
    "CHECK_FAILED",
)
LUSHA_ACTION_TYPES = ("COMPANY_SEARCH", "CONTACT_SEARCH", "EMAIL_REVEAL", "PHONE_REVEAL", "OTHER")
ACTIVITY_TYPES = (
    "COMPANY_CREATED",
    "CAMPAIGN_CREATED",
    "COMPANY_ADDED_TO_CAMPAIGN",
    "CONTACT_ADDED",
    "NOTE_ADDED",
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _timestamps(updated: bool = True) -> list[sa.Column]:
    cols = [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        )
    ]
    if updated:
        cols.append(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            )
        )
    return cols


def upgrade() -> None:
    # ---- users ---------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("odoo_user_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(_in("role", USER_ROLES), name=op.f("ck_users_role_valid")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_odoo_user_id"), "users", ["odoo_user_id"])

    # ---- user_sessions -------------------------------------------------
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(300), nullable=True),
        *_timestamps(updated=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_sessions_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_sessions")),
    )
    op.create_index(op.f("ix_user_sessions_user_id"), "user_sessions", ["user_id"])

    # ---- companies -----------------------------------------------------
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("normalized_name", sa.String(255), nullable=False),
        sa.Column("website", sa.String(500), nullable=True),
        sa.Column("domain", sa.String(255), nullable=True),
        sa.Column("country", sa.String(100), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("industry", sa.String(150), nullable=True),
        sa.Column("main_phone", sa.String(50), nullable=True),
        sa.Column("main_phone_normalized", sa.String(20), nullable=True),
        sa.Column("main_email", sa.String(320), nullable=True),
        sa.Column("company_size", sa.String(20), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_companies_created_by_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_companies")),
    )
    for col in ("normalized_name", "domain", "country", "industry", "main_phone_normalized", "created_by"):
        op.create_index(op.f(f"ix_companies_{col}"), "companies", [col])

    # ---- contacts ------------------------------------------------------
    op.create_table(
        "contacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=True),
        sa.Column("job_title", sa.String(200), nullable=True),
        sa.Column("department", sa.String(100), nullable=True),
        sa.Column("seniority", sa.String(50), nullable=True),
        sa.Column("business_email", sa.String(320), nullable=True),
        sa.Column("business_phone", sa.String(50), nullable=True),
        sa.Column("linkedin_url", sa.String(500), nullable=True),
        sa.Column("source", sa.String(40), server_default="MANUAL", nullable=False),
        sa.Column("source_reference", sa.String(255), nullable=True),
        sa.Column("data_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name=op.f("fk_contacts_company_id_companies"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_contacts_created_by_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contacts")),
    )
    op.create_index(op.f("ix_contacts_company_id"), "contacts", ["company_id"])
    op.create_index(op.f("ix_contacts_business_email"), "contacts", ["business_email"])

    # ---- campaigns -----------------------------------------------------
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("tecomsa_division", sa.String(16), nullable=False),
        sa.Column("country", sa.String(100), nullable=False),
        sa.Column("region", sa.String(100), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("industry", sa.String(150), nullable=True),
        sa.Column("company_size_min", sa.Integer(), nullable=True),
        sa.Column("company_size_max", sa.Integer(), nullable=True),
        sa.Column(
            "target_roles",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("target_company_count", sa.Integer(), nullable=False),
        sa.Column("max_lusha_credit_budget", sa.Integer(), nullable=True),
        sa.Column("additional_instructions", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), server_default="DRAFT", nullable=False),
        *_timestamps(),
        sa.CheckConstraint(_in("tecomsa_division", DIVISIONS), name=op.f("ck_campaigns_division_valid")),
        sa.CheckConstraint(_in("status", CAMPAIGN_STATUSES), name=op.f("ck_campaigns_status_valid")),
        sa.CheckConstraint("target_company_count > 0", name=op.f("ck_campaigns_target_count_positive")),
        sa.CheckConstraint(
            "max_lusha_credit_budget IS NULL OR max_lusha_credit_budget >= 0",
            name=op.f("ck_campaigns_lusha_budget_non_negative"),
        ),
        sa.CheckConstraint(
            "company_size_min IS NULL OR company_size_max IS NULL OR company_size_min <= company_size_max",
            name=op.f("ck_campaigns_company_size_range"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_campaigns_created_by_users"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campaigns")),
    )
    op.create_index(op.f("ix_campaigns_created_by"), "campaigns", ["created_by"])
    op.create_index(op.f("ix_campaigns_tecomsa_division"), "campaigns", ["tecomsa_division"])
    op.create_index(op.f("ix_campaigns_status"), "campaigns", ["status"])

    # ---- campaign_companies --------------------------------------------
    op.create_table(
        "campaign_companies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), server_default="ADDED", nullable=False),
        sa.Column("qualification_status", sa.String(16), server_default="PENDING", nullable=False),
        sa.Column("added_by", sa.Integer(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            _in("status", CAMPAIGN_COMPANY_STATUSES), name=op.f("ck_campaign_companies_status_valid")
        ),
        sa.CheckConstraint(
            _in("qualification_status", QUALIFICATION_STATUSES),
            name=op.f("ck_campaign_companies_qualification_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["campaigns.id"],
            name=op.f("fk_campaign_companies_campaign_id_campaigns"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"],
            name=op.f("fk_campaign_companies_company_id_companies"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["added_by"], ["users.id"], name=op.f("fk_campaign_companies_added_by_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campaign_companies")),
        sa.UniqueConstraint("campaign_id", "company_id", name="uq_campaign_companies_campaign_company"),
    )
    op.create_index(op.f("ix_campaign_companies_campaign_id"), "campaign_companies", ["campaign_id"])
    op.create_index(op.f("ix_campaign_companies_company_id"), "campaign_companies", ["company_id"])

    # ---- odoo_matches --------------------------------------------------
    op.create_table(
        "odoo_matches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("odoo_partner_id", sa.Integer(), nullable=True),
        sa.Column("odoo_lead_id", sa.Integer(), nullable=True),
        sa.Column("match_status", sa.String(32), server_default="NOT_CHECKED", nullable=False),
        sa.Column("match_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("match_reason", sa.Text(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(updated=False),
        sa.CheckConstraint(
            _in("match_status", ODOO_MATCH_STATUSES), name=op.f("ck_odoo_matches_match_status_valid")
        ),
        sa.CheckConstraint(
            "match_confidence IS NULL OR (match_confidence >= 0 AND match_confidence <= 1)",
            name=op.f("ck_odoo_matches_match_confidence_range"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name=op.f("fk_odoo_matches_company_id_companies"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_odoo_matches")),
    )
    op.create_index(op.f("ix_odoo_matches_company_id"), "odoo_matches", ["company_id"])
    op.create_index(op.f("ix_odoo_matches_odoo_partner_id"), "odoo_matches", ["odoo_partner_id"])
    op.create_index(op.f("ix_odoo_matches_odoo_lead_id"), "odoo_matches", ["odoo_lead_id"])

    # ---- lusha_usage ---------------------------------------------------
    op.create_table(
        "lusha_usage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("campaign_id", sa.Integer(), nullable=True),
        sa.Column("company_id", sa.Integer(), nullable=True),
        sa.Column("contact_id", sa.Integer(), nullable=True),
        sa.Column("action_type", sa.String(32), nullable=False),
        sa.Column("credits_used", sa.Integer(), server_default="0", nullable=False),
        sa.Column("provider_request_id", sa.String(255), nullable=True),
        *_timestamps(updated=False),
        sa.CheckConstraint(
            _in("action_type", LUSHA_ACTION_TYPES), name=op.f("ck_lusha_usage_action_type_valid")
        ),
        sa.CheckConstraint("credits_used >= 0", name=op.f("ck_lusha_usage_credits_non_negative")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_lusha_usage_user_id_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["campaigns.id"], name=op.f("fk_lusha_usage_campaign_id_campaigns"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name=op.f("fk_lusha_usage_company_id_companies"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"], name=op.f("fk_lusha_usage_contact_id_contacts"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lusha_usage")),
    )
    op.create_index(op.f("ix_lusha_usage_user_id"), "lusha_usage", ["user_id"])
    op.create_index(op.f("ix_lusha_usage_campaign_id"), "lusha_usage", ["campaign_id"])
    op.create_index(op.f("ix_lusha_usage_company_id"), "lusha_usage", ["company_id"])

    # ---- lead_activities -----------------------------------------------
    op.create_table(
        "lead_activities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=True),
        sa.Column("contact_id", sa.Integer(), nullable=True),
        sa.Column("campaign_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("activity_type", sa.String(40), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(updated=False),
        sa.CheckConstraint(
            _in("activity_type", ACTIVITY_TYPES), name=op.f("ck_lead_activities_activity_type_valid")
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name=op.f("fk_lead_activities_company_id_companies"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"], name=op.f("fk_lead_activities_contact_id_contacts"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["campaigns.id"], name=op.f("fk_lead_activities_campaign_id_campaigns"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_lead_activities_user_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lead_activities")),
    )
    op.create_index(op.f("ix_lead_activities_company_id"), "lead_activities", ["company_id"])
    op.create_index(op.f("ix_lead_activities_campaign_id"), "lead_activities", ["campaign_id"])
    op.create_index(op.f("ix_lead_activities_user_id"), "lead_activities", ["user_id"])

    # ---- audit_logs ----------------------------------------------------
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=True),
        sa.Column("entity_id", sa.String(64), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        *_timestamps(updated=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_audit_logs_user_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index(op.f("ix_audit_logs_user_id"), "audit_logs", ["user_id"])
    op.create_index(op.f("ix_audit_logs_action"), "audit_logs", ["action"])


def downgrade() -> None:
    for table in (
        "audit_logs",
        "lead_activities",
        "lusha_usage",
        "odoo_matches",
        "campaign_companies",
        "campaigns",
        "contacts",
        "companies",
        "user_sessions",
        "users",
    ):
        op.drop_table(table)
