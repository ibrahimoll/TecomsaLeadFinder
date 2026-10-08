"""Discovery quality: confidence, evidence and rejection states

Discovery results get a discovery confidence (HIGH/MEDIUM/LOW) with the evidence,
concerns and business-scale signals behind it, and new states for records that are
kept in the history but not saved (closed, wrong industry, low confidence, possible
Odoo match) or folded into another result (merged branch). Companies keep their
latest discovery assessment.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0006'
down_revision: Union[str, None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_STATES = ("'AVAILABLE', 'EXISTING_LEADFINDER', 'EXISTING_ODOO_CONTACT', 'EXISTING_CRM_LEAD', "
               "'OPEN_OPPORTUNITY', 'CUSTOMER', 'LOST_OPPORTUNITY', 'PROTECTED', 'DUPLICATE'")
_NEW_STATES = (_OLD_STATES + ", 'POSSIBLE_ODOO_MATCH', 'MERGED_BRANCH', 'CLOSED', 'WRONG_INDUSTRY', "
               "'LOW_CONFIDENCE'")


def _jsonb_list(name: str) -> sa.Column:
    return sa.Column(name, postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"),
                     nullable=False)


def upgrade() -> None:
    op.add_column('discovery_results', sa.Column('confidence', sa.String(length=8), nullable=True))
    op.add_column('discovery_results', _jsonb_list('evidence'))
    op.add_column('discovery_results', _jsonb_list('concerns'))
    op.add_column('discovery_results', _jsonb_list('signals'))
    op.create_check_constraint(op.f('ck_discovery_results_confidence_valid'), 'discovery_results',
                               "confidence IN ('HIGH', 'MEDIUM', 'LOW')")
    op.drop_constraint(op.f('ck_discovery_results_state_valid'), 'discovery_results', type_='check')
    op.create_check_constraint(op.f('ck_discovery_results_state_valid'), 'discovery_results',
                               f"state IN ({_NEW_STATES})")
    op.add_column('companies', sa.Column('discovery_confidence', sa.String(length=8), nullable=True))
    op.add_column('companies', sa.Column('discovery_evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('companies', 'discovery_evidence')
    op.drop_column('companies', 'discovery_confidence')
    op.execute("DELETE FROM discovery_results WHERE state IN "
               "('POSSIBLE_ODOO_MATCH', 'MERGED_BRANCH', 'CLOSED', 'WRONG_INDUSTRY', 'LOW_CONFIDENCE')")
    op.drop_constraint(op.f('ck_discovery_results_state_valid'), 'discovery_results', type_='check')
    op.create_check_constraint(op.f('ck_discovery_results_state_valid'), 'discovery_results',
                               f"state IN ({_OLD_STATES})")
    op.drop_constraint(op.f('ck_discovery_results_confidence_valid'), 'discovery_results', type_='check')
    op.drop_column('discovery_results', 'signals')
    op.drop_column('discovery_results', 'concerns')
    op.drop_column('discovery_results', 'evidence')
    op.drop_column('discovery_results', 'confidence')
