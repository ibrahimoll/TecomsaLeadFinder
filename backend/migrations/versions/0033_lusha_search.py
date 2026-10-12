"""Lusha free-text search: a search is cached by its key (company + normalized words + has-phone toggle + page) and
keeps the filters it sent; one run of the same search at a time (was: one per company).

Revision ID: 0033
Revises: 0032
Create Date: 2026-10-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0033'
down_revision: Union[str, None] = '0032'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('lusha_requests', sa.Column('search_key', sa.String(length=300), nullable=True))
    op.add_column('lusha_requests', sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.execute("UPDATE lusha_requests SET search_key = company_id || '||0|0' WHERE action = 'search'")
    op.create_index(op.f('ix_lusha_requests_search_key'), 'lusha_requests', ['search_key'], unique=False)
    op.drop_index('uq_lusha_requests_search', table_name='lusha_requests',
                  postgresql_where=sa.text("action = 'search' AND status = 'pending'"))
    op.create_index('uq_lusha_requests_search', 'lusha_requests', ['search_key'], unique=True,
                    postgresql_where=sa.text("action = 'search' AND status = 'pending'"))


def downgrade() -> None:
    op.drop_index('uq_lusha_requests_search', table_name='lusha_requests',
                  postgresql_where=sa.text("action = 'search' AND status = 'pending'"))
    op.create_index('uq_lusha_requests_search', 'lusha_requests', ['company_id'], unique=True,
                    postgresql_where=sa.text("action = 'search' AND status = 'pending'"))
    op.drop_index(op.f('ix_lusha_requests_search_key'), table_name='lusha_requests')
    op.drop_column('lusha_requests', 'params')
    op.drop_column('lusha_requests', 'search_key')
