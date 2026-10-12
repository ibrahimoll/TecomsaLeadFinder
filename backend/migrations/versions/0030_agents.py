"""Agents: the Profiler's brief / description per company and the Scout's learned lead score.

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0030'
down_revision: Union[str, None] = '0029'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('companies', sa.Column('brief', sa.String(300)))
    op.add_column('companies', sa.Column('profile', sa.Text()))
    op.add_column('companies', sa.Column('profiled_at', sa.DateTime(timezone=True)))
    op.add_column('companies', sa.Column('profile_meta', postgresql.JSONB()))
    op.add_column('companies', sa.Column('scout_score', sa.SmallInteger()))
    op.add_column('companies', sa.Column('scout_reasons', postgresql.JSONB()))


def downgrade() -> None:
    for col in ('scout_reasons', 'scout_score', 'profile_meta', 'profiled_at', 'profile', 'brief'):
        op.drop_column('companies', col)
