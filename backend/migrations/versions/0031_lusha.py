"""Lusha: the ledger of paid Lusha calls (lusha_requests) and a 'lusha' provenance for the contacts a user revealed
from Lusha (paid data: never expired by retention).

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0031'
down_revision: Union[str, None] = '0030'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD = "provenance IN ('public', 'predicted', 'verified', 'human_confirmed', 'internal_crm', 'contributed', 'licensed')"
_NEW = ("provenance IN ('public', 'predicted', 'verified', 'human_confirmed', 'internal_crm', 'contributed', 'licensed', "
        "'lusha')")


def _provenance(rule: str) -> None:
    for table in ('emails', 'phones'):
        op.drop_constraint(op.f(f'ck_{table}_provenance_valid'), table, type_='check')
        op.create_check_constraint(op.f(f'ck_{table}_provenance_valid'), table, rule)


def upgrade() -> None:
    _provenance(_NEW)
    op.create_table('lusha_requests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('person_id', sa.Integer(), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('action', sa.String(length=10), nullable=False),
    sa.Column('lusha_contact_id', sa.String(length=200), nullable=True),
    sa.Column('status', sa.String(length=12), server_default='pending', nullable=False),
    sa.Column('credits', sa.Integer(), server_default='0', nullable=False),
    sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('error', sa.String(length=300), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("action IN ('search', 'email', 'phone')", name=op.f('ck_lusha_requests_action_valid')),
    sa.CheckConstraint("status IN ('pending', 'done', 'not_found', 'failed')", name=op.f('ck_lusha_requests_status_valid')),
    sa.CheckConstraint('credits >= 0', name=op.f('ck_lusha_requests_credits_non_negative')),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_lusha_requests_company_id_companies'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], name=op.f('fk_lusha_requests_person_id_people'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_lusha_requests_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_lusha_requests'))
    )
    op.create_index(op.f('ix_lusha_requests_company_id'), 'lusha_requests', ['company_id'], unique=False)
    op.create_index(op.f('ix_lusha_requests_user_id'), 'lusha_requests', ['user_id'], unique=False)
    op.create_index('uq_lusha_requests_reveal', 'lusha_requests', ['lusha_contact_id', 'action'], unique=True,
                    postgresql_where=sa.text("action <> 'search' AND status IN ('pending', 'done')"))
    op.create_index('uq_lusha_requests_search', 'lusha_requests', ['company_id'], unique=True,
                    postgresql_where=sa.text("action = 'search' AND status = 'pending'"))


def downgrade() -> None:
    op.drop_table('lusha_requests')
    for table in ('emails', 'phones'):
        op.execute(f"UPDATE {table} SET provenance = 'licensed' WHERE provenance = 'lusha'")
    _provenance(_OLD)
