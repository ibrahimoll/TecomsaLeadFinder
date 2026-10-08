"""Company research (Phase 2): research runs and qualifications

company_research_runs: website validation, crawl and structured evidence of one research.
company_qualifications: the TECOMSA fit (Odoo / Frinzo) computed from a run, with the AI
provider, model and versions that produced it. Nothing existing is changed.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0010'
down_revision: Union[str, None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('company_research_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('initiated_by', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('force', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('website_url', sa.String(length=500), nullable=True),
    sa.Column('final_url', sa.String(length=1000), nullable=True),
    sa.Column('website_status', sa.String(length=20), nullable=True),
    sa.Column('website_detail', sa.Text(), nullable=True),
    sa.Column('http_status', sa.Integer(), nullable=True),
    sa.Column('https_ok', sa.Boolean(), nullable=True),
    sa.Column('validated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('crawl_started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('crawl_finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('pages_crawled', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('pages', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=True),
    sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('excerpts', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('failed_stage', sa.String(length=20), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('QUEUED', 'RESEARCHING', 'RESEARCHED', 'COMPLETED', 'RESEARCH_FAILED', 'QUALIFICATION_FAILED')", name=op.f('ck_company_research_runs_status_valid')),
    sa.CheckConstraint("website_status IS NULL OR website_status IN ('ACTIVE', 'REDIRECTED', 'PLACEHOLDER', 'PARKED', 'FOR_SALE', 'EMPTY', 'UNREACHABLE', 'BLOCKED', 'NO_WEBSITE', 'VALIDATION_FAILED')", name=op.f('ck_company_research_runs_website_valid')),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_company_research_runs_company_id_companies'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['initiated_by'], ['users.id'], name=op.f('fk_company_research_runs_initiated_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_company_research_runs'))
    )
    op.create_index(op.f('ix_company_research_runs_company_id'), 'company_research_runs', ['company_id'], unique=False)
    op.create_index(op.f('ix_company_research_runs_initiated_by'), 'company_research_runs', ['initiated_by'], unique=False)
    op.create_index(op.f('ix_company_research_runs_status'), 'company_research_runs', ['status'], unique=False)
    op.create_table('company_qualifications',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('research_run_id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('provider', sa.String(length=40), nullable=False),
    sa.Column('model', sa.String(length=100), nullable=True),
    sa.Column('qualification_version', sa.String(length=20), nullable=False),
    sa.Column('rubric_version', sa.String(length=20), nullable=False),
    sa.Column('input_hash', sa.String(length=64), nullable=False),
    sa.Column('reused_from_id', sa.Integer(), nullable=True),
    sa.Column('odoo_fit_score', sa.Integer(), nullable=False),
    sa.Column('odoo_confidence', sa.String(length=8), nullable=False),
    sa.Column('odoo_reasons', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('recommended_modules', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('frinzo_fit_score', sa.Integer(), nullable=False),
    sa.Column('frinzo_confidence', sa.String(length=8), nullable=False),
    sa.Column('frinzo_reasons', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('frinzo_use_cases', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('scale_signal', sa.String(length=10), nullable=False),
    sa.Column('scale_reasons', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('qualification_status', sa.String(length=24), nullable=False),
    sa.Column('priority', sa.String(length=8), nullable=False),
    sa.Column('status_reason', sa.Text(), nullable=True),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('rejected_evidence', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("frinzo_confidence IN ('HIGH', 'MEDIUM', 'LOW')", name=op.f('ck_company_qualifications_frinzo_confidence_valid')),
    sa.CheckConstraint("odoo_confidence IN ('HIGH', 'MEDIUM', 'LOW')", name=op.f('ck_company_qualifications_odoo_confidence_valid')),
    sa.CheckConstraint("priority IN ('HIGH', 'MEDIUM', 'LOW')", name=op.f('ck_company_qualifications_priority_valid')),
    sa.CheckConstraint("qualification_status IN ('QUALIFIED', 'NEEDS_REVIEW', 'LOW_PRIORITY', 'INSUFFICIENT_EVIDENCE')", name=op.f('ck_company_qualifications_status_valid')),
    sa.CheckConstraint("scale_signal IN ('STRONG', 'MODERATE', 'LIMITED', 'UNKNOWN')", name=op.f('ck_company_qualifications_scale_valid')),
    sa.CheckConstraint('odoo_fit_score BETWEEN 0 AND 100 AND frinzo_fit_score BETWEEN 0 AND 100', name=op.f('ck_company_qualifications_scores_valid')),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_company_qualifications_company_id_companies'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['research_run_id'], ['company_research_runs.id'], name=op.f('fk_company_qualifications_research_run_id_company_research_runs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['reused_from_id'], ['company_qualifications.id'], name=op.f('fk_company_qualifications_reused_from_id_company_qualifications'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_company_qualifications')),
    sa.UniqueConstraint('research_run_id', name=op.f('uq_company_qualifications_research_run_id'))
    )
    op.create_index(op.f('ix_company_qualifications_company_id'), 'company_qualifications', ['company_id'], unique=False)
    op.create_index(op.f('ix_company_qualifications_input_hash'), 'company_qualifications', ['input_hash'], unique=False)
    op.create_index(op.f('ix_company_qualifications_qualification_status'), 'company_qualifications', ['qualification_status'], unique=False)
    op.create_index(op.f('ix_company_qualifications_scale_signal'), 'company_qualifications', ['scale_signal'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_company_qualifications_scale_signal'), table_name='company_qualifications')
    op.drop_index(op.f('ix_company_qualifications_qualification_status'), table_name='company_qualifications')
    op.drop_index(op.f('ix_company_qualifications_input_hash'), table_name='company_qualifications')
    op.drop_index(op.f('ix_company_qualifications_company_id'), table_name='company_qualifications')
    op.drop_table('company_qualifications')
    op.drop_index(op.f('ix_company_research_runs_status'), table_name='company_research_runs')
    op.drop_index(op.f('ix_company_research_runs_initiated_by'), table_name='company_research_runs')
    op.drop_index(op.f('ix_company_research_runs_company_id'), table_name='company_research_runs')
    op.drop_table('company_research_runs')
