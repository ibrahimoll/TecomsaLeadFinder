"""Odoo import foundation

Adds salespeople, import_runs, odoo_contacts and crm_leads; extends companies with
source, address, email domain, CRM relationship status and owning salesperson; and
replaces the odoo_matches status set with relationship-oriented statuses.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_MATCH_STATUSES = (
    "NOT_CHECKED", "NEW", "EXISTING_CONTACT", "EXISTING_CUSTOMER", "ACTIVE_OPPORTUNITY",
    "PREVIOUSLY_CONTACTED", "POSSIBLE_DUPLICATE", "CHECK_FAILED",
)
NEW_MATCH_STATUSES = (
    "NOT_CHECKED", "AVAILABLE", "EXISTING_CONTACT", "EXISTING_LEAD", "EXISTING_OPPORTUNITY",
    "CUSTOMER", "LOST_OPPORTUNITY", "PREVIOUSLY_CONTACTED", "CHECK_FAILED",
)
# old -> new (and the reverse for downgrade)
STATUS_UPGRADE = {"NEW": "AVAILABLE", "EXISTING_CUSTOMER": "CUSTOMER",
                  "ACTIVE_OPPORTUNITY": "EXISTING_OPPORTUNITY", "POSSIBLE_DUPLICATE": "NOT_CHECKED"}
STATUS_DOWNGRADE = {"AVAILABLE": "NEW", "CUSTOMER": "EXISTING_CUSTOMER",
                    "EXISTING_OPPORTUNITY": "ACTIVE_OPPORTUNITY", "EXISTING_LEAD": "ACTIVE_OPPORTUNITY",
                    "LOST_OPPORTUNITY": "PREVIOUSLY_CONTACTED"}
IMPORT_TYPES = ("ODOO_CRM", "ODOO_CONTACTS")
IMPORT_STATUSES = ("PREVIEW", "COMPLETED", "FAILED", "CANCELLED")
LEAD_TYPES = ("LEAD", "OPPORTUNITY")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def _remap_match_status(mapping: dict[str, str]) -> None:
    for old, new in mapping.items():
        op.execute(sa.text("UPDATE odoo_matches SET match_status = :new WHERE match_status = :old")
                   .bindparams(new=new, old=old))


def upgrade() -> None:
    # ---- salespeople ---------------------------------------------------
    op.create_table(
        "salespeople",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("name_key", sa.String(200), nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("odoo_user_id", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_salespeople_user_id_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_salespeople")),
    )
    op.create_index(op.f("ix_salespeople_user_id"), "salespeople", ["user_id"], unique=True)
    op.create_index(op.f("ix_salespeople_name_key"), "salespeople", ["name_key"], unique=True)
    op.create_index(op.f("ix_salespeople_odoo_user_id"), "salespeople", ["odoo_user_id"])

    # ---- companies: new columns ----------------------------------------
    op.add_column("companies", sa.Column("address", sa.String(500), nullable=True))
    op.add_column("companies", sa.Column("email_domain", sa.String(255), nullable=True))
    op.add_column("companies", sa.Column("source", sa.String(40), server_default="MANUAL", nullable=False))
    op.add_column("companies", sa.Column("source_reference", sa.String(255), nullable=True))
    op.add_column("companies", sa.Column("odoo_contact_id", sa.Integer(), nullable=True))
    op.add_column("companies", sa.Column("crm_status", sa.String(32), server_default="NOT_CHECKED", nullable=False))
    op.add_column("companies", sa.Column("crm_status_reason", sa.Text(), nullable=True))
    op.add_column("companies", sa.Column("crm_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("companies", sa.Column("salesperson_id", sa.Integer(), nullable=True))
    op.create_foreign_key(op.f("fk_companies_salesperson_id_salespeople"), "companies", "salespeople",
                          ["salesperson_id"], ["id"], ondelete="SET NULL")
    for col in ("email_domain", "source", "odoo_contact_id", "crm_status", "salesperson_id"):
        op.create_index(op.f(f"ix_companies_{col}"), "companies", [col])
    # Backfill: email domain from the existing main_email; demo seed companies get source DEMO.
    op.execute("UPDATE companies SET email_domain = lower(split_part(main_email, '@', 2)) "
               "WHERE main_email LIKE '%@%'")
    op.execute("UPDATE companies SET source = 'DEMO' WHERE description LIKE 'FICTIONAL development seed record%'")

    # ---- odoo_matches: relationship-oriented statuses -------------------
    op.drop_constraint(op.f("ck_odoo_matches_match_status_valid"), "odoo_matches", type_="check")
    _remap_match_status(STATUS_UPGRADE)
    op.create_check_constraint(op.f("ck_odoo_matches_match_status_valid"), "odoo_matches",
                               _in("match_status", NEW_MATCH_STATUSES))
    op.execute(
        "UPDATE companies c SET crm_status = m.match_status, crm_checked_at = m.checked_at "
        "FROM (SELECT DISTINCT ON (company_id) company_id, match_status, checked_at FROM odoo_matches "
        "ORDER BY company_id, created_at DESC, id DESC) m WHERE m.company_id = c.id"
    )

    # ---- import_runs ---------------------------------------------------
    op.create_table(
        "import_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("import_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), server_default="PREVIEW", nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("stored_filename", sa.String(255), nullable=False),
        sa.Column("file_type", sa.String(8), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("column_mapping", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("detected_columns", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        *[sa.Column(c, sa.Integer(), server_default="0", nullable=False) for c in (
            "row_count", "valid_count", "warning_count", "duplicate_count", "inserted_count",
            "updated_count", "skipped_count", "error_count", "companies_created", "companies_linked")],
        sa.Column("issues", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("failure_reason", sa.String(1000), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(_in("import_type", IMPORT_TYPES), name=op.f("ck_import_runs_import_type_valid")),
        sa.CheckConstraint(_in("status", IMPORT_STATUSES), name=op.f("ck_import_runs_status_valid")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_import_runs_created_by_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_runs")),
    )
    for col in ("import_type", "status", "sha256", "created_by"):
        op.create_index(op.f(f"ix_import_runs_{col}"), "import_runs", [col])

    # ---- odoo_contacts -------------------------------------------------
    op.create_table(
        "odoo_contacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_key", sa.String(128), nullable=False),
        sa.Column("odoo_contact_id", sa.Integer(), nullable=True),
        sa.Column("odoo_external_id", sa.String(255), nullable=True),
        sa.Column("contact_name", sa.String(255), nullable=False),
        sa.Column("is_company", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("parent_company", sa.String(255), nullable=True),
        sa.Column("website", sa.String(500), nullable=True),
        sa.Column("domain", sa.String(255), nullable=True),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("mobile", sa.String(50), nullable=True),
        sa.Column("phone_normalized", sa.String(20), nullable=True),
        sa.Column("address", sa.String(500), nullable=True),
        sa.Column("country", sa.String(100), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("is_customer", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("salesperson_name", sa.String(200), nullable=True),
        sa.Column("salesperson_id", sa.Integer(), nullable=True),
        sa.Column("company_key", sa.String(255), nullable=True),
        sa.Column("email_domain", sa.String(255), nullable=True),
        sa.Column("company_id", sa.Integer(), nullable=True),
        sa.Column("import_run_id", sa.Integer(), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["salesperson_id"], ["salespeople.id"], name=op.f("fk_odoo_contacts_salesperson_id_salespeople"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name=op.f("fk_odoo_contacts_company_id_companies"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["import_run_id"], ["import_runs.id"], name=op.f("fk_odoo_contacts_import_run_id_import_runs"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_odoo_contacts")),
        sa.UniqueConstraint("source_key", name=op.f("uq_odoo_contacts_source_key")),
    )
    for col in ("odoo_contact_id", "domain", "phone_normalized", "salesperson_id", "company_key",
                "email_domain", "company_id"):
        op.create_index(op.f(f"ix_odoo_contacts_{col}"), "odoo_contacts", [col])

    # ---- crm_leads -----------------------------------------------------
    op.create_table(
        "crm_leads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_key", sa.String(128), nullable=False),
        sa.Column("odoo_lead_id", sa.Integer(), nullable=True),
        sa.Column("odoo_external_id", sa.String(255), nullable=True),
        sa.Column("opportunity_name", sa.String(500), nullable=False),
        sa.Column("company_name", sa.String(255), nullable=True),
        sa.Column("contact_name", sa.String(255), nullable=True),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("mobile", sa.String(50), nullable=True),
        sa.Column("website", sa.String(500), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("country", sa.String(100), nullable=True),
        sa.Column("salesperson_name", sa.String(200), nullable=True),
        sa.Column("salesperson_id", sa.Integer(), nullable=True),
        sa.Column("sales_team", sa.String(200), nullable=True),
        sa.Column("stage", sa.String(200), nullable=True),
        sa.Column("lead_type", sa.String(16), server_default="OPPORTUNITY", nullable=False),
        sa.Column("expected_revenue", sa.Numeric(16, 2), nullable=True),
        sa.Column("probability", sa.Numeric(5, 2), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("is_won", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("lost_reason", sa.Text(), nullable=True),
        sa.Column("created_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_activity", sa.DateTime(timezone=True), nullable=True),
        sa.Column("company_key", sa.String(255), nullable=True),
        sa.Column("domain", sa.String(255), nullable=True),
        sa.Column("email_domain", sa.String(255), nullable=True),
        sa.Column("phone_normalized", sa.String(20), nullable=True),
        sa.Column("company_id", sa.Integer(), nullable=True),
        sa.Column("import_run_id", sa.Integer(), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(_in("lead_type", LEAD_TYPES), name=op.f("ck_crm_leads_lead_type_valid")),
        sa.ForeignKeyConstraint(["salesperson_id"], ["salespeople.id"], name=op.f("fk_crm_leads_salesperson_id_salespeople"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name=op.f("fk_crm_leads_company_id_companies"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["import_run_id"], ["import_runs.id"], name=op.f("fk_crm_leads_import_run_id_import_runs"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_crm_leads")),
        sa.UniqueConstraint("source_key", name=op.f("uq_crm_leads_source_key")),
    )
    for col in ("odoo_lead_id", "salesperson_id", "company_key", "domain", "email_domain",
                "phone_normalized", "company_id"):
        op.create_index(op.f(f"ix_crm_leads_{col}"), "crm_leads", [col])


def downgrade() -> None:
    op.drop_table("crm_leads")
    op.drop_table("odoo_contacts")
    op.drop_table("import_runs")

    op.drop_constraint(op.f("ck_odoo_matches_match_status_valid"), "odoo_matches", type_="check")
    _remap_match_status(STATUS_DOWNGRADE)
    op.create_check_constraint(op.f("ck_odoo_matches_match_status_valid"), "odoo_matches",
                               _in("match_status", OLD_MATCH_STATUSES))

    for col in ("email_domain", "source", "odoo_contact_id", "crm_status", "salesperson_id"):
        op.drop_index(op.f(f"ix_companies_{col}"), table_name="companies")
    op.drop_constraint(op.f("fk_companies_salesperson_id_salespeople"), "companies", type_="foreignkey")
    for col in ("salesperson_id", "crm_checked_at", "crm_status_reason", "crm_status", "odoo_contact_id",
                "source_reference", "source", "email_domain", "address"):
        op.drop_column("companies", col)

    op.drop_table("salespeople")
