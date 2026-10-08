"""Query-driven company search: company_domains (current / alternate / historical domains, one company each) and
search analytics on company_lookups (the parsed query, where the answer came from, why nothing was found).

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0023'
down_revision: Union[str, None] = '0022'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'company_domains',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('domain', sa.String(length=253), nullable=False),
        sa.Column('status', sa.String(length=12), server_default='alternate', nullable=False),
        sa.Column('source_id', sa.BigInteger(), nullable=True),
        sa.Column('first_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("status IN ('current', 'alternate', 'historical')", name=op.f('ck_company_domains_status_valid')),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_company_domains_company_id_companies'),
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_id'], ['sources.id'], name=op.f('fk_company_domains_source_id_sources'),
                                ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_company_domains')),
        sa.UniqueConstraint('domain', name=op.f('uq_company_domains_domain')),
    )
    op.create_index(op.f('ix_company_domains_company_id'), 'company_domains', ['company_id'], unique=False)
    op.execute("INSERT INTO company_domains (company_id, domain, status) SELECT id, domain, 'current' FROM companies "
               "WHERE domain IS NOT NULL ON CONFLICT DO NOTHING")
    op.add_column('company_lookups', sa.Column('parsed', postgresql.JSONB(astext_type=sa.Text()),
                                               server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.add_column('company_lookups', sa.Column('resolved_from', sa.String(length=30), nullable=True))
    op.add_column('company_lookups', sa.Column('failure_reason', sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column('company_lookups', 'failure_reason')
    op.drop_column('company_lookups', 'resolved_from')
    op.drop_column('company_lookups', 'parsed')
    op.drop_index(op.f('ix_company_domains_company_id'), table_name='company_domains')
    op.drop_table('company_domains')
