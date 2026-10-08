"""Automatic company discovery

Adds discovery runs (one per "Find companies" search), their examined results with the
state LeadFinder concluded, per-company source provenance (company_sources), and the
location and creating run on companies.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('discovery_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('country', sa.String(length=2), nullable=False),
    sa.Column('city', sa.String(length=50), nullable=True),
    sa.Column('industry', sa.String(length=50), nullable=True),
    sa.Column('custom_query', sa.String(length=200), nullable=True),
    sa.Column('query_label', sa.String(length=300), nullable=False),
    sa.Column('requested_count', sa.Integer(), nullable=False),
    sa.Column('sources', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('source_version', sa.String(length=200), nullable=True),
    sa.Column('status', sa.String(length=16), server_default='QUEUED', nullable=False),
    sa.Column('progress', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('source_match_count', sa.Integer(), nullable=False),
    sa.Column('raw_results_count', sa.Integer(), nullable=False),
    sa.Column('duplicate_count', sa.Integer(), nullable=False),
    sa.Column('existing_company_count', sa.Integer(), nullable=False),
    sa.Column('odoo_protected_count', sa.Integer(), nullable=False),
    sa.Column('new_company_count', sa.Integer(), nullable=False),
    sa.Column('error_count', sa.Integer(), nullable=False),
    sa.Column('errors', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('QUEUED', 'SEARCHING', 'PROCESSING', 'COMPLETED', 'PARTIAL', 'FAILED')", name=op.f('ck_discovery_runs_status_valid')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_discovery_runs_created_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_discovery_runs'))
    )
    op.create_index(op.f('ix_discovery_runs_created_by'), 'discovery_runs', ['created_by'], unique=False)
    op.create_index(op.f('ix_discovery_runs_status'), 'discovery_runs', ['status'], unique=False)
    op.create_table('company_sources',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=40), nullable=False),
    sa.Column('external_id', sa.String(length=255), nullable=False),
    sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('source_version', sa.String(length=200), nullable=True),
    sa.Column('first_seen_run_id', sa.Integer(), nullable=True),
    sa.Column('last_seen_run_id', sa.Integer(), nullable=True),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_company_sources_company_id_companies'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['first_seen_run_id'], ['discovery_runs.id'], name=op.f('fk_company_sources_first_seen_run_id_discovery_runs'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['last_seen_run_id'], ['discovery_runs.id'], name=op.f('fk_company_sources_last_seen_run_id_discovery_runs'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_company_sources')),
    sa.UniqueConstraint('source', 'external_id', name=op.f('uq_company_sources_source'))
    )
    op.create_index(op.f('ix_company_sources_company_id'), 'company_sources', ['company_id'], unique=False)
    op.create_table('discovery_results',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('run_id', sa.Integer(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=40), nullable=False),
    sa.Column('external_id', sa.String(length=255), nullable=True),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('category', sa.String(length=200), nullable=True),
    sa.Column('address', sa.String(length=500), nullable=True),
    sa.Column('city', sa.String(length=100), nullable=True),
    sa.Column('country', sa.String(length=100), nullable=True),
    sa.Column('phone', sa.String(length=50), nullable=True),
    sa.Column('website', sa.String(length=500), nullable=True),
    sa.Column('email', sa.String(length=320), nullable=True),
    sa.Column('latitude', sa.Float(), nullable=True),
    sa.Column('longitude', sa.Float(), nullable=True),
    sa.Column('state', sa.String(length=32), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('match_reason', sa.String(length=300), nullable=True),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('duplicate_of_id', sa.Integer(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("state IN ('AVAILABLE', 'EXISTING_LEADFINDER', 'EXISTING_ODOO_CONTACT', 'EXISTING_CRM_LEAD', 'OPEN_OPPORTUNITY', 'CUSTOMER', 'LOST_OPPORTUNITY', 'PROTECTED', 'DUPLICATE')", name=op.f('ck_discovery_results_state_valid')),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_discovery_results_company_id_companies'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['duplicate_of_id'], ['discovery_results.id'], name=op.f('fk_discovery_results_duplicate_of_id_discovery_results'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['run_id'], ['discovery_runs.id'], name=op.f('fk_discovery_results_run_id_discovery_runs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_discovery_results'))
    )
    op.create_index(op.f('ix_discovery_results_company_id'), 'discovery_results', ['company_id'], unique=False)
    op.create_index(op.f('ix_discovery_results_run_id'), 'discovery_results', ['run_id'], unique=False)
    op.create_index(op.f('ix_discovery_results_state'), 'discovery_results', ['state'], unique=False)
    op.add_column('companies', sa.Column('latitude', sa.Float(), nullable=True))
    op.add_column('companies', sa.Column('longitude', sa.Float(), nullable=True))
    op.add_column('companies', sa.Column('created_by_discovery_run_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_companies_created_by_discovery_run_id'), 'companies', ['created_by_discovery_run_id'], unique=False)
    op.create_foreign_key(op.f('fk_companies_created_by_discovery_run_id_discovery_runs'), 'companies', 'discovery_runs', ['created_by_discovery_run_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint(op.f('fk_companies_created_by_discovery_run_id_discovery_runs'), 'companies', type_='foreignkey')
    op.drop_index(op.f('ix_companies_created_by_discovery_run_id'), table_name='companies')
    op.drop_column('companies', 'created_by_discovery_run_id')
    op.drop_column('companies', 'longitude')
    op.drop_column('companies', 'latitude')
    op.drop_index(op.f('ix_discovery_results_state'), table_name='discovery_results')
    op.drop_index(op.f('ix_discovery_results_run_id'), table_name='discovery_results')
    op.drop_index(op.f('ix_discovery_results_company_id'), table_name='discovery_results')
    op.drop_table('discovery_results')
    op.drop_index(op.f('ix_company_sources_company_id'), table_name='company_sources')
    op.drop_table('company_sources')
    op.drop_index(op.f('ix_discovery_runs_status'), table_name='discovery_runs')
    op.drop_index(op.f('ix_discovery_runs_created_by'), table_name='discovery_runs')
    op.drop_table('discovery_runs')
