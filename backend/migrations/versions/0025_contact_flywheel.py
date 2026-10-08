"""Contact flywheel (Step 6.1): e-mail statuses 'high_confidence_predicted' (a prediction backed by >= 2 real published
addresses of the same pattern) and 'confirmed' (a real reply / a person's confirmation), contact feedback events
from real sales activity, and record-level visibility of TECOMSA internal contacts (owner + restricted) on emails,
phones and roles.

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0025'
down_revision: Union[str, None] = '0024'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD = "'unknown', 'discovered', 'published', 'predicted', 'verified', 'invalid', 'catch_all'"
_NEW = _OLD + ", 'stale', 'high_confidence_predicted', 'confirmed'"
_EVENTS = ("delivered", "hard_bounce", "soft_bounce", "replied", "human_confirmed", "number_confirmed",
           "wrong_number", "company_switchboard", "extension_confirmed", "correct_person", "wrong_person",
           "person_left_company", "title_changed")


def _statuses(values: str, predicted: str) -> None:
    op.drop_constraint(op.f('ck_emails_status_valid'), 'emails', type_='check')
    op.create_check_constraint(op.f('ck_emails_status_valid'), 'emails', f"status IN ({values})")
    op.drop_constraint(op.f('ck_emails_predicted_not_verified'), 'emails', type_='check')
    op.create_check_constraint(op.f('ck_emails_predicted_not_verified'), 'emails',
                               f"status NOT IN ({predicted}) OR last_verified_at IS NULL")


def upgrade() -> None:
    op.alter_column('emails', 'status', type_=sa.String(length=30), existing_type=sa.String(length=16),
                    existing_nullable=False)
    _statuses(_NEW, "'predicted', 'high_confidence_predicted'")
    for table in ('emails', 'phones', 'company_people'):
        op.add_column(table, sa.Column('owner_user_id', sa.Integer(), nullable=True))
        op.create_foreign_key(op.f(f'fk_{table}_owner_user_id_users'), table, 'users', ['owner_user_id'], ['id'],
                              ondelete='SET NULL')
        op.add_column(table, sa.Column('restricted', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.create_table(
        'contact_feedback',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('event', sa.String(length=30), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('person_id', sa.Integer(), nullable=True),
        sa.Column('company_person_id', sa.Integer(), nullable=True),
        sa.Column('email_id', sa.Integer(), nullable=True),
        sa.Column('phone_id', sa.Integer(), nullable=True),
        sa.Column('value', sa.String(length=320), nullable=True),
        sa.Column('note', sa.String(length=500), nullable=True),
        sa.Column('effect', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(f"event IN ({', '.join(repr(e) for e in _EVENTS)})",
                           name=op.f('ck_contact_feedback_event_valid')),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_contact_feedback_company_id_companies'),
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['person_id'], ['people.id'], name=op.f('fk_contact_feedback_person_id_people'),
                                ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['company_person_id'], ['company_people.id'],
                                name=op.f('fk_contact_feedback_company_person_id_company_people'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['email_id'], ['emails.id'], name=op.f('fk_contact_feedback_email_id_emails'),
                                ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['phone_id'], ['phones.id'], name=op.f('fk_contact_feedback_phone_id_phones'),
                                ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_contact_feedback_user_id_users'),
                                ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_contact_feedback')),
    )
    op.create_index(op.f('ix_contact_feedback_company_id'), 'contact_feedback', ['company_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_contact_feedback_company_id'), table_name='contact_feedback')
    op.drop_table('contact_feedback')
    for table in ('company_people', 'phones', 'emails'):
        op.drop_column(table, 'restricted')
        op.drop_constraint(op.f(f'fk_{table}_owner_user_id_users'), table, type_='foreignkey')
        op.drop_column(table, 'owner_user_id')
    op.execute("UPDATE emails SET status = 'predicted' WHERE status = 'high_confidence_predicted'")
    op.execute("UPDATE emails SET status = 'verified', last_verified_at = coalesce(last_verified_at, now()) "
               "WHERE status = 'confirmed'")
    _statuses(_OLD, "'predicted'")
    op.alter_column('emails', 'status', type_=sa.String(length=16), existing_type=sa.String(length=30),
                    existing_nullable=False)
