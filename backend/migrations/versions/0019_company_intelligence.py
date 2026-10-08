"""Master company & people intelligence: a full-text index over the local source corpus, the company relationship
graph (parent / subsidiary / brand...), dated company signals (the timeline) and field completeness per company.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0019'
down_revision: Union[str, None] = '0018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RELATIONS = ("parent", "ultimate_parent", "subsidiary", "brand", "branch", "operating_entity", "holding")


def upgrade() -> None:
    op.add_column('external_documents', sa.Column('search_vector', postgresql.TSVECTOR(), nullable=True))
    op.create_index('ix_external_documents_search_vector', 'external_documents', ['search_vector'],
                    postgresql_using='gin')
    op.create_table('company_relationships',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('related_company_id', sa.Integer(), nullable=True),
    sa.Column('related_name', sa.String(length=300), nullable=False),
    sa.Column('relation_type', sa.String(length=30), nullable=False),
    sa.Column('source_id', sa.BigInteger(), nullable=False),
    sa.Column('confidence', sa.SmallInteger(), nullable=True),
    sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("relation_type IN (" + ", ".join(f"'{r}'" for r in RELATIONS) + ")",
                       name=op.f('ck_company_relationships_relation_type_valid')),
    sa.CheckConstraint('confidence IS NULL OR (confidence >= 0 AND confidence <= 100)',
                       name=op.f('ck_company_relationships_confidence_range')),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_company_relationships_company_id_companies'),
                            ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['related_company_id'], ['companies.id'],
                            name=op.f('fk_company_relationships_related_company_id_companies'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], name=op.f('fk_company_relationships_source_id_sources'),
                            ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_company_relationships')),
    sa.UniqueConstraint('company_id', 'relation_type', 'related_name', name='uq_company_relationships_company_relation')
    )
    op.create_index(op.f('ix_company_relationships_company_id'), 'company_relationships', ['company_id'])
    op.create_index(op.f('ix_company_relationships_related_company_id'), 'company_relationships',
                    ['related_company_id'])
    op.add_column('company_signals', sa.Column('event_date', sa.Date(), nullable=True))
    op.add_column('company_signals', sa.Column('description', sa.Text(), nullable=True))
    op.add_column('company_signals', sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_index('ix_company_signals_company_event_date', 'company_signals', ['company_id', 'event_date'])
    op.add_column('companies', sa.Column('completeness', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('companies', 'completeness')
    op.drop_index('ix_company_signals_company_event_date', table_name='company_signals')
    op.drop_column('company_signals', 'detail')
    op.drop_column('company_signals', 'description')
    op.drop_column('company_signals', 'event_date')
    op.drop_index(op.f('ix_company_relationships_related_company_id'), table_name='company_relationships')
    op.drop_index(op.f('ix_company_relationships_company_id'), table_name='company_relationships')
    op.drop_table('company_relationships')
    op.drop_index('ix_external_documents_search_vector', table_name='external_documents')
    op.drop_column('external_documents', 'search_vector')
