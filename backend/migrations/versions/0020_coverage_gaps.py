"""Coverage-gap expansion: why a company has no people (gap reasons), first-class multilingual company aliases,
per-lookup source diagnostics (Common Crawl index calls...), and the deep people-research cooldown on companies.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0020'
down_revision: Union[str, None] = '0019'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('company_gap_reasons',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('gap_reason', sa.String(length=40), nullable=False),
    sa.Column('source_key', sa.String(length=60), nullable=True),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('detected_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_company_gap_reasons_company_id_companies'),
                            ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_company_gap_reasons')),
    )
    op.create_index('uq_company_gap_reasons_company_reason_source', 'company_gap_reasons',
                    ['company_id', 'gap_reason', 'source_key'], unique=True, postgresql_nulls_not_distinct=True)
    op.create_table('company_aliases',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('alias', sa.String(length=300), nullable=False),
    sa.Column('normalized_alias', sa.String(length=300), nullable=False),
    sa.Column('language', sa.String(length=8), nullable=True),
    sa.Column('alias_type', sa.String(length=20), nullable=False),
    sa.Column('source_id', sa.BigInteger(), nullable=True),
    sa.Column('confidence', sa.SmallInteger(), nullable=True),
    sa.Column('is_manual', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("alias_type IN ('legal', 'brand', 'trading', 'arabic', 'english', 'french', 'abbreviation', "
                       "'historical', 'source_variant')", name=op.f('ck_company_aliases_alias_type_valid')),
    sa.CheckConstraint('confidence IS NULL OR (confidence >= 0 AND confidence <= 100)',
                       name=op.f('ck_company_aliases_confidence_range')),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_company_aliases_company_id_companies'),
                            ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], name=op.f('fk_company_aliases_source_id_sources'),
                            ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_company_aliases')),
    sa.UniqueConstraint('company_id', 'normalized_alias', name='uq_company_aliases_company_normalized'),
    )
    op.create_index(op.f('ix_company_aliases_normalized_alias'), 'company_aliases', ['normalized_alias'])
    op.create_table('source_lookups',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('source_key', sa.String(length=60), nullable=False),
    sa.Column('target', sa.String(length=500), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('failure_reason', sa.String(length=40), nullable=True),
    sa.Column('items', sa.Integer(), nullable=True),
    sa.Column('useful_items', sa.Integer(), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('cached', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_source_lookups_company_id_companies'),
                            ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_source_lookups')),
    )
    op.create_index(op.f('ix_source_lookups_company_id'), 'source_lookups', ['company_id'])
    op.create_index('ix_source_lookups_source_created', 'source_lookups', ['source_key', 'created_at'])
    op.add_column('companies', sa.Column('deep_research_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('companies', sa.Column('next_research_eligible_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('companies', sa.Column('sources_attempted', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('companies', 'sources_attempted')
    op.drop_column('companies', 'next_research_eligible_at')
    op.drop_column('companies', 'deep_research_at')
    op.drop_index('ix_source_lookups_source_created', table_name='source_lookups')
    op.drop_index(op.f('ix_source_lookups_company_id'), table_name='source_lookups')
    op.drop_table('source_lookups')
    op.drop_index(op.f('ix_company_aliases_normalized_alias'), table_name='company_aliases')
    op.drop_table('company_aliases')
    op.drop_index('uq_company_gap_reasons_company_reason_source', table_name='company_gap_reasons')
    op.drop_table('company_gap_reasons')
