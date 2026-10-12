"""Licensed directory imports (5INDEX, Yelleb... exports): a 'licensed' provenance for the contacts a licensed
directory states - neither public web data nor TECOMSA's own; removed with their import, never expired by retention.

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-09
"""
from typing import Sequence, Union

from alembic import op

revision: str = '0029'
down_revision: Union[str, None] = '0028'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD = "provenance IN ('public', 'predicted', 'verified', 'human_confirmed', 'internal_crm', 'contributed')"
_NEW = "provenance IN ('public', 'predicted', 'verified', 'human_confirmed', 'internal_crm', 'contributed', 'licensed')"


def _provenance(rule: str) -> None:
    for table in ('emails', 'phones'):
        op.drop_constraint(op.f(f'ck_{table}_provenance_valid'), table, type_='check')
        op.create_check_constraint(op.f(f'ck_{table}_provenance_valid'), table, rule)


def upgrade() -> None:
    _provenance(_NEW)


def downgrade() -> None:
    for table in ('emails', 'phones'):
        op.execute(f"UPDATE {table} SET provenance = 'contributed' WHERE provenance = 'licensed'")
    _provenance(_OLD)
