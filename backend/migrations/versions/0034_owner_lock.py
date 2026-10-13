"""Owner lock: one row holding the owner key's Argon2 hash (never the key) and whether LeadFinder is locked.

Revision ID: 0034
Revises: 0033
Create Date: 2026-10-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0034'
down_revision: Union[str, None] = '0033'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'owner_lock',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('key_hash', sa.String(length=200), nullable=False),
        sa.Column('locked', sa.Boolean(), nullable=False),
        sa.Column('changed_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint('id = 1', name=op.f('ck_owner_lock_single_row')),
    )


def downgrade() -> None:
    op.drop_table('owner_lock')
