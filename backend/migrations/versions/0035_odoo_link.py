"""Odoo link per company: the CRM lead it was sent to / found as, its stage and outcome (won / lost / open), read back
hourly so sales outcomes in Odoo teach the Scout and existing clients are visible in LeadFinder.

Revision ID: 0035
Revises: 0034
Create Date: 2026-10-13
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0035'
down_revision: Union[str, None] = '0034'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('companies', sa.Column('odoo_lead_id', sa.Integer()))
    op.add_column('companies', sa.Column('odoo_stage', sa.String(80)))
    op.add_column('companies', sa.Column('odoo_outcome', sa.String(8)))  # open | won | lost
    op.add_column('companies', sa.Column('odoo_synced_at', sa.DateTime(timezone=True)))
    op.create_index('ix_companies_odoo_lead_id', 'companies', ['odoo_lead_id'])


def downgrade() -> None:
    op.drop_index('ix_companies_odoo_lead_id', table_name='companies')
    for col in ('odoo_synced_at', 'odoo_outcome', 'odoo_stage', 'odoo_lead_id'):
        op.drop_column('companies', col)
