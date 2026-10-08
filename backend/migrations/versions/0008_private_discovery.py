"""Private discovery: reserved results

A discovery result can be RESERVED: the company is another salesperson's private candidate,
so it is not available to this search. Only managers and admins see those rows.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-01
"""
from typing import Sequence, Union

from alembic import op

revision: str = '0008'
down_revision: Union[str, None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STATES = ("'AVAILABLE', 'EXISTING_LEADFINDER', 'EXISTING_ODOO_CONTACT', 'EXISTING_CRM_LEAD', 'OPEN_OPPORTUNITY', "
           "'CUSTOMER', 'LOST_OPPORTUNITY', 'PROTECTED', 'POSSIBLE_ODOO_MATCH', 'DUPLICATE', 'MERGED_BRANCH', "
           "'CLOSED', 'WRONG_INDUSTRY', 'LOW_CONFIDENCE'")


def _states(sql: str) -> None:
    op.drop_constraint(op.f('ck_discovery_results_state_valid'), 'discovery_results', type_='check')
    op.create_check_constraint(op.f('ck_discovery_results_state_valid'), 'discovery_results', f"state IN ({sql})")


def upgrade() -> None:
    _states(_STATES + ", 'RESERVED'")


def downgrade() -> None:
    op.execute("DELETE FROM discovery_results WHERE state = 'RESERVED'")
    _states(_STATES)
