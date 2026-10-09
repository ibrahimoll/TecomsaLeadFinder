"""Privacy controls: people removed on request are never researched or imported again at that company (only a hash
of the company and the name key is kept).

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0028'
down_revision: Union[str, None] = '0027'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'person_suppressions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('key_hash', sa.String(length=64), nullable=False),
        sa.Column('reason', sa.String(length=300), nullable=False),
        sa.Column('requested_by_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_person_suppressions_company_id_companies'),
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['requested_by_user_id'], ['users.id'],
                                name=op.f('fk_person_suppressions_requested_by_user_id_users'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_person_suppressions')),
        sa.UniqueConstraint('company_id', 'key_hash', name='uq_person_suppressions_company_key'),
    )


def downgrade() -> None:
    op.drop_table('person_suppressions')
