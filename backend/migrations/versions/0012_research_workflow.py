"""Research Company workflow: the salesperson's request and the contact-step outcome

company_research_runs gains: contact_source (FREE / APOLLO / LUSHA), dm_target (+ custom title),
want_email / want_phone (never remembered by the UI), contact_status / contact_summary (the
decision-maker step, run only after the company qualifies), decision_maker_run_id, and
reused_from_run_id (research reused without a new crawl). Existing rows keep NULL / false:
research only.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0012'
down_revision: Union[str, None] = '0011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CHECKS = {
    'contact_source_valid': "contact_source IS NULL OR contact_source IN ('FREE', 'APOLLO', 'LUSHA')",
    'dm_target_valid': "dm_target IS NULL OR dm_target IN ('AUTO', 'OWNER_CEO', 'GENERAL_MANAGER', 'OPERATIONS', "
                       "'FINANCE', 'IT', 'MARKETING', 'CUSTOMER_SERVICE', 'OTHER')",
    'contact_status_valid': "contact_status IS NULL OR contact_status IN ('PENDING', 'RUNNING', 'SKIPPED', "
                            "'COMPLETED', 'PARTIAL', 'FAILED')",
}


def upgrade() -> None:
    op.add_column('company_research_runs', sa.Column('reused_from_run_id', sa.Integer(), nullable=True))
    op.add_column('company_research_runs', sa.Column('contact_source', sa.String(length=10), nullable=True))
    op.add_column('company_research_runs', sa.Column('dm_target', sa.String(length=20), nullable=True))
    op.add_column('company_research_runs', sa.Column('dm_custom_title', sa.String(length=100), nullable=True))
    op.add_column('company_research_runs', sa.Column('want_email', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('company_research_runs', sa.Column('want_phone', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('company_research_runs', sa.Column('contact_status', sa.String(length=16), nullable=True))
    op.add_column('company_research_runs', sa.Column('contact_summary', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.add_column('company_research_runs', sa.Column('decision_maker_run_id', sa.Integer(), nullable=True))
    op.create_foreign_key(op.f('fk_company_research_runs_reused_from_run_id_company_research_runs'), 'company_research_runs', 'company_research_runs', ['reused_from_run_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key(op.f('fk_company_research_runs_decision_maker_run_id_decision_maker_runs'), 'company_research_runs', 'decision_maker_runs', ['decision_maker_run_id'], ['id'], ondelete='SET NULL')
    for name, condition in _CHECKS.items():
        op.create_check_constraint(op.f(f'ck_company_research_runs_{name}'), 'company_research_runs', condition)


def downgrade() -> None:
    for name in _CHECKS:
        op.drop_constraint(op.f(f'ck_company_research_runs_{name}'), 'company_research_runs', type_='check')
    op.drop_constraint(op.f('fk_company_research_runs_decision_maker_run_id_decision_maker_runs'), 'company_research_runs', type_='foreignkey')
    op.drop_constraint(op.f('fk_company_research_runs_reused_from_run_id_company_research_runs'), 'company_research_runs', type_='foreignkey')
    for column in ('decision_maker_run_id', 'contact_summary', 'contact_status', 'want_phone', 'want_email',
                   'dm_custom_title', 'dm_target', 'contact_source', 'reused_from_run_id'):
        op.drop_column('company_research_runs', column)
