"""Candidate ownership: companies.owner_id

The salesperson who owns a discovered candidate (one column, so at most one owner). Set when a
search saves the company; released candidates (NULL) can be claimed again with an atomic
conditional UPDATE. Existing discovered companies are owned by whoever found them.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0009'
down_revision: Union[str, None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('companies', sa.Column('owner_id', sa.Integer(), nullable=True))
    op.create_foreign_key(op.f('fk_companies_owner_id_users'), 'companies', 'users', ['owner_id'], ['id'],
                          ondelete='SET NULL')
    op.create_index(op.f('ix_companies_owner_id'), 'companies', ['owner_id'], unique=False)
    op.execute("UPDATE companies SET owner_id = created_by WHERE source = 'DISCOVERY'")


def downgrade() -> None:
    op.drop_index(op.f('ix_companies_owner_id'), table_name='companies')
    op.drop_constraint(op.f('fk_companies_owner_id_users'), 'companies', type_='foreignkey')
    op.drop_column('companies', 'owner_id')
