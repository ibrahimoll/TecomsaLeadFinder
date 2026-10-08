"""External people discovery (Step 5.1): a shared cache of external public documents and of search results;
external people research status on companies.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0018'
down_revision: Union[str, None] = '0017'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('external_search_cache',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('provider', sa.String(length=30), nullable=False),
    sa.Column('query', sa.String(length=500), nullable=False),
    sa.Column('query_hash', sa.String(length=64), nullable=False),
    sa.Column('results', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_external_search_cache')),
    sa.UniqueConstraint('provider', 'query_hash', name='uq_external_search_cache_query')
    )
    op.create_table('external_documents',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('url', sa.String(length=2000), nullable=False),
    sa.Column('final_url', sa.String(length=2000), nullable=True),
    sa.Column('domain', sa.String(length=253), nullable=True),
    sa.Column('category', sa.String(length=30), nullable=False),
    sa.Column('doc_type', sa.String(length=10), nullable=False),
    sa.Column('title', sa.String(length=500), nullable=True),
    sa.Column('content_hash', sa.String(length=64), nullable=True),
    sa.Column('http_status', sa.SmallInteger(), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('fresh_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('source_id', sa.BigInteger(), nullable=True),
    sa.Column('content', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], name=op.f('fk_external_documents_source_id_sources'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_external_documents')),
    sa.UniqueConstraint('url', name=op.f('uq_external_documents_url'))
    )
    op.create_index(op.f('ix_external_documents_content_hash'), 'external_documents', ['content_hash'], unique=False)
    op.create_index(op.f('ix_external_documents_domain'), 'external_documents', ['domain'], unique=False)
    op.create_index(op.f('ix_external_documents_source_id'), 'external_documents', ['source_id'], unique=False)
    op.add_column('companies', sa.Column('external_people_status', sa.String(length=16), server_default='not_started', nullable=False))
    op.add_column('companies', sa.Column('external_people_message', sa.String(length=300), nullable=True))
    op.add_column('companies', sa.Column('external_people_researched_at', sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(op.f('ck_companies_external_people_status_valid'), 'companies',
                               "external_people_status IN ('not_started', 'queued', 'researching', 'partial', "
                               "'completed', 'failed')")


def downgrade() -> None:
    op.drop_constraint(op.f('ck_companies_external_people_status_valid'), 'companies', type_='check')
    op.drop_column('companies', 'external_people_researched_at')
    op.drop_column('companies', 'external_people_message')
    op.drop_column('companies', 'external_people_status')
    op.drop_index(op.f('ix_external_documents_source_id'), table_name='external_documents')
    op.drop_index(op.f('ix_external_documents_domain'), table_name='external_documents')
    op.drop_index(op.f('ix_external_documents_content_hash'), table_name='external_documents')
    op.drop_table('external_documents')
    op.drop_table('external_search_cache')
