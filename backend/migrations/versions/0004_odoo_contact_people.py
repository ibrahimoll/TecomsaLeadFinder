"""LeadFinder contacts linked to Odoo contacts

People from an Odoo contacts import become LeadFinder contacts of their company.
`contacts.odoo_contact_id` links each to its Odoo record (unique, so re-imports update
instead of duplicating; ON DELETE CASCADE, so deleting the Odoo record removes it).

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("contacts", sa.Column("odoo_contact_id", sa.Integer(), nullable=True))
    op.create_foreign_key(op.f("fk_contacts_odoo_contact_id_odoo_contacts"), "contacts", "odoo_contacts",
                          ["odoo_contact_id"], ["id"], ondelete="CASCADE")
    op.create_unique_constraint(op.f("uq_contacts_odoo_contact_id"), "contacts", ["odoo_contact_id"])


def downgrade() -> None:
    op.execute("DELETE FROM contacts WHERE odoo_contact_id IS NOT NULL")
    op.drop_constraint(op.f("uq_contacts_odoo_contact_id"), "contacts", type_="unique")
    op.drop_constraint(op.f("fk_contacts_odoo_contact_id_odoo_contacts"), "contacts", type_="foreignkey")
    op.drop_column("contacts", "odoo_contact_id")
