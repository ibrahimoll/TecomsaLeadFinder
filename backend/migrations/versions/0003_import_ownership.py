"""Import ownership and contact job position

Records which import first created each Odoo record, company and salesperson so an
import can be deleted together with the data only it brought in. Adds the job
position of Odoo contacts.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("odoo_contacts", "crm_leads", "companies", "salespeople")


def upgrade() -> None:
    op.add_column("odoo_contacts", sa.Column("job_position", sa.String(length=200), nullable=True))
    for table in TABLES:
        op.add_column(table, sa.Column("created_by_import_id", sa.Integer(), nullable=True))
        op.create_foreign_key(op.f(f"fk_{table}_created_by_import_id_import_runs"), table, "import_runs",
                              ["created_by_import_id"], ["id"], ondelete="SET NULL")
        op.create_index(op.f(f"ix_{table}_created_by_import_id"), table, ["created_by_import_id"])
    for table in ("odoo_contacts", "crm_leads"):
        op.create_index(op.f(f"ix_{table}_import_run_id"), table, ["import_run_id"])
        # Best effort for existing rows: the latest import is the only one recorded.
        op.execute(f"UPDATE {table} SET created_by_import_id = import_run_id")
    op.execute(
        "UPDATE companies c SET created_by_import_id = r.id FROM import_runs r "
        "WHERE c.source = 'ODOO_IMPORT' AND c.source_reference = 'odoo-import:' || r.id"
    )
    op.execute(
        "UPDATE salespeople s SET created_by_import_id = ("
        " SELECT min(x.run) FROM ("
        "  SELECT import_run_id AS run FROM crm_leads WHERE salesperson_id = s.id"
        "  UNION ALL SELECT import_run_id FROM odoo_contacts WHERE salesperson_id = s.id) x)"
    )


def downgrade() -> None:
    for table in ("odoo_contacts", "crm_leads"):
        op.drop_index(op.f(f"ix_{table}_import_run_id"), table_name=table)
    for table in TABLES:
        op.drop_index(op.f(f"ix_{table}_created_by_import_id"), table_name=table)
        op.drop_constraint(op.f(f"fk_{table}_created_by_import_id_import_runs"), table, type_="foreignkey")
        op.drop_column(table, "created_by_import_id")
    op.drop_column("odoo_contacts", "job_position")
