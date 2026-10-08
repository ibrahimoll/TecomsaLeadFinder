"""Company enrichment (Step 4): company signals, products and services, fetched web pages, research status on
companies, contact purposes, location names / phones, job priorities.

Every existing company starts as enrichment_status 'not_started' (researched when opened or found again).

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0016'
down_revision: Union[str, None] = '0015'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('company_products_services',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('raw_name', sa.String(length=200), nullable=False),
    sa.Column('normalized_name', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('source_id', sa.BigInteger(), nullable=False),
    sa.Column('confidence', sa.SmallInteger(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('product', 'service', 'category')", name=op.f('ck_company_products_services_kind_valid')),
    sa.CheckConstraint('confidence IS NULL OR confidence BETWEEN 0 AND 100', name=op.f('ck_company_products_services_confidence_range')),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_company_products_services_company_id_companies'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], name=op.f('fk_company_products_services_source_id_sources'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_company_products_services')),
    sa.UniqueConstraint('company_id', 'kind', 'normalized_name', name='uq_company_products_services_name')
    )
    op.create_index(op.f('ix_company_products_services_company_id'), 'company_products_services', ['company_id'], unique=False)
    op.create_index(op.f('ix_company_products_services_source_id'), 'company_products_services', ['source_id'], unique=False)
    op.create_table('company_web_pages',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('url', sa.String(length=2000), nullable=False),
    sa.Column('canonical_url', sa.String(length=2000), nullable=True),
    sa.Column('title', sa.String(length=500), nullable=True),
    sa.Column('page_type', sa.String(length=30), nullable=False),
    sa.Column('http_status', sa.SmallInteger(), nullable=True),
    sa.Column('content_hash', sa.String(length=64), nullable=True),
    sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('fresh_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('extractor_version', sa.SmallInteger(), nullable=True),
    sa.Column('source_id', sa.BigInteger(), nullable=True),
    sa.Column('content', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_company_web_pages_company_id_companies'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], name=op.f('fk_company_web_pages_source_id_sources'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_company_web_pages')),
    sa.UniqueConstraint('company_id', 'url', name='uq_company_web_pages_company_url')
    )
    op.create_index(op.f('ix_company_web_pages_company_id'), 'company_web_pages', ['company_id'], unique=False)
    op.create_index(op.f('ix_company_web_pages_source_id'), 'company_web_pages', ['source_id'], unique=False)
    op.create_table('company_signals',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('signal_type', sa.String(length=60), nullable=False),
    sa.Column('signal_value', sa.String(length=300), nullable=True),
    sa.Column('confidence', sa.SmallInteger(), nullable=True),
    sa.Column('source_id', sa.BigInteger(), nullable=False),
    sa.Column('evidence_id', sa.BigInteger(), nullable=True),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('confidence IS NULL OR confidence BETWEEN 0 AND 100', name=op.f('ck_company_signals_confidence_range')),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_company_signals_company_id_companies'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['evidence_id'], ['evidence.id'], name=op.f('fk_company_signals_evidence_id_evidence'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], name=op.f('fk_company_signals_source_id_sources'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_company_signals'))
    )
    op.create_index(op.f('ix_company_signals_company_id'), 'company_signals', ['company_id'], unique=False)
    op.create_index(op.f('ix_company_signals_signal_type'), 'company_signals', ['signal_type'], unique=False)
    op.create_index(op.f('ix_company_signals_source_id'), 'company_signals', ['source_id'], unique=False)
    op.create_index('uq_company_signals_company_type_value', 'company_signals', ['company_id', 'signal_type', 'signal_value'], unique=True, postgresql_nulls_not_distinct=True)
    op.add_column('companies', sa.Column('youtube_url', sa.String(length=500), nullable=True))
    op.add_column('companies', sa.Column('tiktok_url', sa.String(length=500), nullable=True))
    op.add_column('companies', sa.Column('twitter_url', sa.String(length=500), nullable=True))
    op.add_column('companies', sa.Column('employee_count_min', sa.Integer(), nullable=True))
    op.add_column('companies', sa.Column('employee_count_max', sa.Integer(), nullable=True))
    op.add_column('companies', sa.Column('enrichment_status', sa.String(length=16), server_default='not_started', nullable=False))
    op.add_column('companies', sa.Column('enrichment_message', sa.String(length=300), nullable=True))
    op.add_column('companies', sa.Column('enrichment_started_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('companies', sa.Column('enrichment_completed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('companies', sa.Column('last_enriched_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('companies', sa.Column('enrichment_version', sa.SmallInteger(), nullable=True))
    op.add_column('companies', sa.Column('website_confidence', sa.SmallInteger(), nullable=True))
    op.create_check_constraint(op.f('ck_companies_enrichment_status_valid'), 'companies',
                               "enrichment_status IN ('not_started', 'queued', 'researching', 'partial', 'completed', "
                               "'failed')")
    op.create_check_constraint(op.f('ck_companies_employee_range_ordered'), 'companies',
                               'employee_count_min IS NULL OR employee_count_max IS NULL OR '
                               'employee_count_min <= employee_count_max')
    op.create_check_constraint(op.f('ck_companies_website_confidence_range'), 'companies',
                               'website_confidence IS NULL OR website_confidence BETWEEN 0 AND 100')
    op.add_column('company_locations', sa.Column('name', sa.String(length=200), nullable=True))
    op.add_column('company_locations', sa.Column('phone', sa.String(length=50), nullable=True))
    op.add_column('emails', sa.Column('purpose', sa.String(length=20), nullable=True))
    op.add_column('phones', sa.Column('purpose', sa.String(length=20), nullable=True))
    op.add_column('research_runs', sa.Column('priority', sa.SmallInteger(), server_default='50', nullable=False))
    op.drop_index(op.f('ix_research_runs_queued'), table_name='research_runs', postgresql_where="((status)::text = 'queued'::text)")
    op.create_index('ix_research_runs_queued', 'research_runs', ['priority', 'created_at'], unique=False, postgresql_where=sa.text("status = 'queued'"))
    op.create_index('uq_research_runs_queued_company', 'research_runs', ['company_id', 'research_type'], unique=True, postgresql_where=sa.text("status = 'queued' AND company_id IS NOT NULL"))


def downgrade() -> None:
    op.drop_index('uq_research_runs_queued_company', table_name='research_runs', postgresql_where=sa.text("status = 'queued' AND company_id IS NOT NULL"))
    op.drop_index('ix_research_runs_queued', table_name='research_runs', postgresql_where=sa.text("status = 'queued'"))
    op.create_index(op.f('ix_research_runs_queued'), 'research_runs', ['created_at'], unique=False, postgresql_where="((status)::text = 'queued'::text)")
    op.drop_column('research_runs', 'priority')
    op.drop_column('phones', 'purpose')
    op.drop_column('emails', 'purpose')
    op.drop_column('company_locations', 'phone')
    op.drop_column('company_locations', 'name')
    op.drop_constraint(op.f('ck_companies_website_confidence_range'), 'companies', type_='check')
    op.drop_constraint(op.f('ck_companies_employee_range_ordered'), 'companies', type_='check')
    op.drop_constraint(op.f('ck_companies_enrichment_status_valid'), 'companies', type_='check')
    op.drop_column('companies', 'website_confidence')
    op.drop_column('companies', 'enrichment_version')
    op.drop_column('companies', 'last_enriched_at')
    op.drop_column('companies', 'enrichment_completed_at')
    op.drop_column('companies', 'enrichment_started_at')
    op.drop_column('companies', 'enrichment_message')
    op.drop_column('companies', 'enrichment_status')
    op.drop_column('companies', 'employee_count_max')
    op.drop_column('companies', 'employee_count_min')
    op.drop_column('companies', 'twitter_url')
    op.drop_column('companies', 'tiktok_url')
    op.drop_column('companies', 'youtube_url')
    op.drop_index('uq_company_signals_company_type_value', table_name='company_signals', postgresql_nulls_not_distinct=True)
    op.drop_index(op.f('ix_company_signals_source_id'), table_name='company_signals')
    op.drop_index(op.f('ix_company_signals_signal_type'), table_name='company_signals')
    op.drop_index(op.f('ix_company_signals_company_id'), table_name='company_signals')
    op.drop_table('company_signals')
    op.drop_index(op.f('ix_company_web_pages_source_id'), table_name='company_web_pages')
    op.drop_index(op.f('ix_company_web_pages_company_id'), table_name='company_web_pages')
    op.drop_table('company_web_pages')
    op.drop_index(op.f('ix_company_products_services_source_id'), table_name='company_products_services')
    op.drop_index(op.f('ix_company_products_services_company_id'), table_name='company_products_services')
    op.drop_table('company_products_services')
