"""Decision-makers and contact enrichment (Phase 3)

decision_maker_runs, decision_makers (canonical people per salesperson scope),
decision_maker_sources (provenance; unique per provider id, company and scope) and
enrichment_requests (usage ledger; partial unique index = one live/successful paid request per
person, action and version, so a double click never pays twice). Nothing existing is changed.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0011'
down_revision: Union[str, None] = '0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('decision_makers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=True),
    sa.Column('first_name', sa.String(length=100), nullable=False),
    sa.Column('last_name', sa.String(length=100), nullable=True),
    sa.Column('last_name_obfuscated', sa.String(length=100), nullable=True),
    sa.Column('normalized_name', sa.String(length=200), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=True),
    sa.Column('role_family', sa.String(length=40), nullable=False),
    sa.Column('department', sa.String(length=100), nullable=True),
    sa.Column('seniority', sa.String(length=20), nullable=False),
    sa.Column('employment_status', sa.String(length=10), nullable=False),
    sa.Column('needs_review', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('review_reason', sa.Text(), nullable=True),
    sa.Column('linkedin_url', sa.String(length=500), nullable=True),
    sa.Column('location', sa.String(length=200), nullable=True),
    sa.Column('work_email', sa.String(length=320), nullable=True),
    sa.Column('email_status', sa.String(length=16), nullable=False),
    sa.Column('email_provider', sa.String(length=20), nullable=True),
    sa.Column('email_detail', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('phone', sa.String(length=32), nullable=True),
    sa.Column('phone_status', sa.String(length=16), nullable=False),
    sa.Column('phone_provider', sa.String(length=20), nullable=True),
    sa.Column('phone_type', sa.String(length=20), nullable=True),
    sa.Column('phone_dnc', sa.Boolean(), nullable=True),
    sa.Column('assessment', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('best_score', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('ranks', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("email_status IN ('NOT_SEARCHED', 'AVAILABLE', 'VERIFIED', 'UNVERIFIED', 'NOT_FOUND')", name=op.f('ck_decision_makers_email_status_valid')),
    sa.CheckConstraint("employment_status IN ('CURRENT', 'FORMER', 'UNKNOWN')", name=op.f('ck_decision_makers_employment_valid')),
    sa.CheckConstraint("phone_status IN ('NOT_SEARCHED', 'PENDING', 'AVAILABLE', 'NOT_FOUND')", name=op.f('ck_decision_makers_phone_status_valid')),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_decision_makers_company_id_companies'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_decision_makers_owner_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_decision_makers'))
    )
    op.create_index(op.f('ix_decision_makers_company_id'), 'decision_makers', ['company_id'], unique=False)
    op.create_index('ix_decision_makers_scope', 'decision_makers', ['owner_id', 'company_id'], unique=False)
    op.create_table('decision_maker_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('initiated_by', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('solutions', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('target_roles', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('providers', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('override', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('override_reason', sa.Text(), nullable=True),
    sa.Column('research_run_id', sa.Integer(), nullable=True),
    sa.Column('people_found', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('QUEUED', 'SEARCHING', 'FOUND', 'PARTIAL', 'NO_MATCH', 'NEEDS_REVIEW', 'FAILED')", name=op.f('ck_decision_maker_runs_status_valid')),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_decision_maker_runs_company_id_companies'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['initiated_by'], ['users.id'], name=op.f('fk_decision_maker_runs_initiated_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['research_run_id'], ['company_research_runs.id'], name=op.f('fk_decision_maker_runs_research_run_id_company_research_runs'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_decision_maker_runs'))
    )
    op.create_index(op.f('ix_decision_maker_runs_company_id'), 'decision_maker_runs', ['company_id'], unique=False)
    op.create_index(op.f('ix_decision_maker_runs_initiated_by'), 'decision_maker_runs', ['initiated_by'], unique=False)
    op.create_index(op.f('ix_decision_maker_runs_status'), 'decision_maker_runs', ['status'], unique=False)
    op.create_table('decision_maker_sources',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('person_id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=True),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('run_id', sa.Integer(), nullable=True),
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('external_id', sa.String(length=255), nullable=False),
    sa.Column('source_url', sa.String(length=1000), nullable=True),
    sa.Column('observed_name', sa.String(length=255), nullable=False),
    sa.Column('observed_title', sa.String(length=255), nullable=True),
    sa.Column('observed_company', sa.String(length=255), nullable=True),
    sa.Column('observed_domain', sa.String(length=255), nullable=True),
    sa.Column('employment_status', sa.String(length=10), nullable=False),
    sa.Column('provider_confidence', sa.String(length=20), nullable=True),
    sa.Column('provider_updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('excerpt', sa.Text(), nullable=True),
    sa.Column('raw', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("employment_status IN ('CURRENT', 'FORMER', 'UNKNOWN')", name=op.f('ck_decision_maker_sources_employment_valid')),
    sa.CheckConstraint("provider IN ('WEBSITE', 'APOLLO', 'LUSHA')", name=op.f('ck_decision_maker_sources_provider_valid')),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_decision_maker_sources_company_id_companies'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_decision_maker_sources_owner_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['person_id'], ['decision_makers.id'], name=op.f('fk_decision_maker_sources_person_id_decision_makers'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['run_id'], ['decision_maker_runs.id'], name=op.f('fk_decision_maker_sources_run_id_decision_maker_runs'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_decision_maker_sources'))
    )
    op.create_index(op.f('ix_decision_maker_sources_person_id'), 'decision_maker_sources', ['person_id'], unique=False)
    op.create_index(op.f('ix_decision_maker_sources_run_id'), 'decision_maker_sources', ['run_id'], unique=False)
    op.create_index('uq_decision_maker_sources_external', 'decision_maker_sources', ['owner_id', 'company_id', 'provider', 'external_id'], unique=True)
    op.create_table('enrichment_requests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('person_id', sa.Integer(), nullable=True),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('run_id', sa.Integer(), nullable=True),
    sa.Column('initiated_by', sa.Integer(), nullable=True),
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('action', sa.String(length=32), nullable=False),
    sa.Column('field', sa.String(length=10), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('estimated_credits', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('confirmed_credits', sa.Integer(), nullable=True),
    sa.Column('provider_request_id', sa.String(length=255), nullable=True),
    sa.Column('webhook_token_hash', sa.String(length=64), nullable=True),
    sa.Column('detail', sa.Text(), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("action IN ('APOLLO_PEOPLE_SEARCH', 'APOLLO_EMAIL', 'APOLLO_PHONE', 'LUSHA_EMAIL', 'LUSHA_PHONE')", name=op.f('ck_enrichment_requests_action_valid')),
    sa.CheckConstraint("status IN ('PENDING', 'AWAITING_WEBHOOK', 'ENRICHED', 'NOT_FOUND', 'FAILED', 'BUDGET_LIMIT_REACHED', 'DISABLED')", name=op.f('ck_enrichment_requests_status_valid')),
    sa.CheckConstraint('estimated_credits >= 0', name=op.f('ck_enrichment_requests_credits_non_negative')),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_enrichment_requests_company_id_companies'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['initiated_by'], ['users.id'], name=op.f('fk_enrichment_requests_initiated_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['person_id'], ['decision_makers.id'], name=op.f('fk_enrichment_requests_person_id_decision_makers'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['run_id'], ['decision_maker_runs.id'], name=op.f('fk_enrichment_requests_run_id_decision_maker_runs'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_enrichment_requests')),
    sa.UniqueConstraint('webhook_token_hash', name=op.f('uq_enrichment_requests_webhook_token_hash'))
    )
    op.create_index(op.f('ix_enrichment_requests_company_id'), 'enrichment_requests', ['company_id'], unique=False)
    op.create_index(op.f('ix_enrichment_requests_initiated_by'), 'enrichment_requests', ['initiated_by'], unique=False)
    op.create_index(op.f('ix_enrichment_requests_person_id'), 'enrichment_requests', ['person_id'], unique=False)
    op.create_index(op.f('ix_enrichment_requests_provider'), 'enrichment_requests', ['provider'], unique=False)
    op.create_index(op.f('ix_enrichment_requests_status'), 'enrichment_requests', ['status'], unique=False)
    op.create_index('uq_enrichment_requests_live', 'enrichment_requests', ['person_id', 'action', 'version'], unique=True, postgresql_where=sa.text("status IN ('PENDING', 'AWAITING_WEBHOOK', 'ENRICHED')"))


def downgrade() -> None:
    op.drop_index('uq_enrichment_requests_live', table_name='enrichment_requests', postgresql_where=sa.text("status IN ('PENDING', 'AWAITING_WEBHOOK', 'ENRICHED')"))
    op.drop_index(op.f('ix_enrichment_requests_status'), table_name='enrichment_requests')
    op.drop_index(op.f('ix_enrichment_requests_provider'), table_name='enrichment_requests')
    op.drop_index(op.f('ix_enrichment_requests_person_id'), table_name='enrichment_requests')
    op.drop_index(op.f('ix_enrichment_requests_initiated_by'), table_name='enrichment_requests')
    op.drop_index(op.f('ix_enrichment_requests_company_id'), table_name='enrichment_requests')
    op.drop_table('enrichment_requests')
    op.drop_index('uq_decision_maker_sources_external', table_name='decision_maker_sources')
    op.drop_index(op.f('ix_decision_maker_sources_run_id'), table_name='decision_maker_sources')
    op.drop_index(op.f('ix_decision_maker_sources_person_id'), table_name='decision_maker_sources')
    op.drop_table('decision_maker_sources')
    op.drop_index(op.f('ix_decision_maker_runs_status'), table_name='decision_maker_runs')
    op.drop_index(op.f('ix_decision_maker_runs_initiated_by'), table_name='decision_maker_runs')
    op.drop_index(op.f('ix_decision_maker_runs_company_id'), table_name='decision_maker_runs')
    op.drop_table('decision_maker_runs')
    op.drop_index('ix_decision_makers_scope', table_name='decision_makers')
    op.drop_index(op.f('ix_decision_makers_company_id'), table_name='decision_makers')
    op.drop_table('decision_makers')
