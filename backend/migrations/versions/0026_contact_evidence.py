"""Contact network (Step 6.2): the evidence trail of every e-mail / phone (contact_evidence: published, predicted,
imported from TECOMSA, delivered, replied, bounced, confirmed... accumulated, never replaced) and idempotent feedback
events (contact_feedback.event_key: a delivery / bounce / reply notification applied once).

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0026'
down_revision: Union[str, None] = '0025'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('contact_feedback', sa.Column('event_key', sa.String(length=200), nullable=True))
    op.create_index(op.f('ix_contact_feedback_event_key'), 'contact_feedback', ['event_key'], unique=True)
    op.create_table(
        'contact_evidence',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('email_id', sa.Integer(), nullable=True),
        sa.Column('phone_id', sa.Integer(), nullable=True),
        sa.Column('kind', sa.String(length=30), nullable=False),
        sa.Column('source_id', sa.BigInteger(), nullable=True),
        sa.Column('feedback_id', sa.BigInteger(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('detail', sa.String(length=300), nullable=True),
        sa.Column('observed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('num_nonnulls(email_id, phone_id) = 1', name=op.f('ck_contact_evidence_one_contact')),
        sa.ForeignKeyConstraint(['email_id'], ['emails.id'], name=op.f('fk_contact_evidence_email_id_emails'),
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['phone_id'], ['phones.id'], name=op.f('fk_contact_evidence_phone_id_phones'),
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_id'], ['sources.id'], name=op.f('fk_contact_evidence_source_id_sources'),
                                ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['feedback_id'], ['contact_feedback.id'],
                                name=op.f('fk_contact_evidence_feedback_id_contact_feedback'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_contact_evidence_user_id_users'),
                                ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_contact_evidence')),
    )
    op.create_index(op.f('ix_contact_evidence_email_id'), 'contact_evidence', ['email_id'])
    op.create_index(op.f('ix_contact_evidence_phone_id'), 'contact_evidence', ['phone_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_contact_evidence_phone_id'), table_name='contact_evidence')
    op.drop_index(op.f('ix_contact_evidence_email_id'), table_name='contact_evidence')
    op.drop_table('contact_evidence')
    op.drop_index(op.f('ix_contact_feedback_event_key'), table_name='contact_feedback')
    op.drop_column('contact_feedback', 'event_key')
