"""Contact intelligence (Step 6): an explicit 'published' email status, the provenance of every email / phone
(public / predicted / verified / human_confirmed / internal_crm), how an email was checked (verification), the
company e-mail patterns observed on real published addresses, and the contact-research state of a company.

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0024'
down_revision: Union[str, None] = '0023'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_EMAIL_OLD = "'unknown', 'discovered', 'predicted', 'verified', 'invalid', 'catch_all'"
_EMAIL_NEW = "'unknown', 'discovered', 'published', 'predicted', 'verified', 'invalid', 'catch_all'"
_PROVENANCE = "provenance IN ('public', 'predicted', 'verified', 'human_confirmed', 'internal_crm')"
_STATUS = "'not_started', 'queued', 'researching', 'partial', 'completed', 'failed', 'timed_out'"


def _email_statuses(values: str) -> None:
    op.drop_constraint(op.f('ck_emails_status_valid'), 'emails', type_='check')
    op.create_check_constraint(op.f('ck_emails_status_valid'), 'emails', f"status IN ({values})")


def upgrade() -> None:
    _email_statuses(_EMAIL_NEW)
    op.execute("UPDATE emails SET status = 'published' WHERE status = 'discovered' "
               "OR (status = 'unknown' AND is_public AND source_id IS NOT NULL)")
    for table in ('emails', 'phones'):
        op.add_column(table, sa.Column('provenance', sa.String(length=20), server_default='public', nullable=False))
        op.create_check_constraint(op.f(f'ck_{table}_provenance_valid'), table, _PROVENANCE)
    op.execute("UPDATE emails SET provenance = 'predicted' WHERE status = 'predicted'")
    op.add_column('emails', sa.Column('verification', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('emails', sa.Column('evidence', sa.String(length=500), nullable=True))
    op.add_column('phones', sa.Column('evidence', sa.String(length=500), nullable=True))
    op.alter_column('phones', 'phone_type', type_=sa.String(length=30), existing_type=sa.String(length=20))
    op.create_table(
        'company_email_patterns',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('domain', sa.String(length=253), nullable=False),
        sa.Column('pattern', sa.String(length=40), nullable=False),
        sa.Column('sample_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('confidence', sa.SmallInteger(), nullable=True),
        sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"),
                  nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'],
                                name=op.f('fk_company_email_patterns_company_id_companies'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_company_email_patterns')),
        sa.UniqueConstraint('company_id', 'domain', 'pattern', name='uq_company_email_patterns_company_domain_pattern'),
    )
    op.add_column('companies', sa.Column('contact_status', sa.String(length=16), server_default='not_started',
                                         nullable=False))
    op.add_column('companies', sa.Column('contact_message', sa.String(length=300), nullable=True))
    op.add_column('companies', sa.Column('contact_researched_at', sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(op.f('ck_companies_contact_status_valid'), 'companies',
                               f"contact_status IN ({_STATUS})")


def downgrade() -> None:
    op.drop_constraint(op.f('ck_companies_contact_status_valid'), 'companies', type_='check')
    for column in ('contact_researched_at', 'contact_message', 'contact_status'):
        op.drop_column('companies', column)
    op.drop_table('company_email_patterns')
    op.execute("UPDATE phones SET phone_type = 'office' WHERE length(phone_type) > 20")
    op.alter_column('phones', 'phone_type', type_=sa.String(length=20), existing_type=sa.String(length=30))
    op.drop_column('phones', 'evidence')
    op.drop_column('emails', 'evidence')
    op.drop_column('emails', 'verification')
    for table in ('emails', 'phones'):
        op.drop_constraint(op.f(f'ck_{table}_provenance_valid'), table, type_='check')
        op.drop_column(table, 'provenance')
    op.execute("UPDATE emails SET status = 'discovered' WHERE status = 'published'")
    _email_statuses(_EMAIL_OLD)
