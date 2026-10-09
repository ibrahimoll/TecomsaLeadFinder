"""Contributions (Step 6.3): explicit visibility of TECOMSA / contributed contacts and roles (organization, managers:
the owner + managers / admins, private: the owner only) instead of a restricted flag, and a 'contributed' provenance
for contacts a user contributes (business cards, e-mail signatures, meeting contacts, manual entries) - protected from
research like TECOMSA CRM data.

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0027'
down_revision: Union[str, None] = '0026'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD = "provenance IN ('public', 'predicted', 'verified', 'human_confirmed', 'internal_crm')"
_NEW = "provenance IN ('public', 'predicted', 'verified', 'human_confirmed', 'internal_crm', 'contributed')"
_TABLES = ('emails', 'phones', 'company_people')


def _provenance(rule: str) -> None:
    for table in ('emails', 'phones'):
        op.drop_constraint(op.f(f'ck_{table}_provenance_valid'), table, type_='check')
        op.create_check_constraint(op.f(f'ck_{table}_provenance_valid'), table, rule)


def upgrade() -> None:
    _provenance(_NEW)
    for table in _TABLES:
        op.add_column(table, sa.Column('visibility', sa.String(length=20), server_default='organization',
                                       nullable=False))
        op.execute(f"UPDATE {table} SET visibility = 'managers' WHERE restricted")
        op.create_check_constraint(op.f(f'ck_{table}_visibility_valid'), table,
                                   "visibility IN ('organization', 'managers', 'private')")
        op.drop_column(table, 'restricted')


def downgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column('restricted', sa.Boolean(), server_default=sa.false(), nullable=False))
        op.execute(f"UPDATE {table} SET restricted = visibility <> 'organization'")
        op.drop_constraint(op.f(f'ck_{table}_visibility_valid'), table, type_='check')
        op.drop_column(table, 'visibility')
    for table in ('emails', 'phones'):
        op.execute(f"UPDATE {table} SET provenance = 'internal_crm' WHERE provenance = 'contributed'")
    _provenance(_OLD)
