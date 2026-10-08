"""People discovery (Step 5): employment status, title rank, confidence components and human corrections on
company_people; people research status / coverage on companies; possible duplicate people; profile URL.

Existing roles keep their meaning: is_current -> 'current', otherwise 'former'.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0017'
down_revision: Union[str, None] = '0016'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('possible_duplicate_people',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('person_id', sa.Integer(), nullable=False),
    sa.Column('other_person_id', sa.Integer(), nullable=False),
    sa.Column('reason', sa.String(length=300), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='open', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('open', 'merged', 'distinct')", name=op.f('ck_possible_duplicate_people_status_valid')),
    sa.CheckConstraint('person_id < other_person_id', name=op.f('ck_possible_duplicate_people_ordered_pair')),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_possible_duplicate_people_company_id_companies'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['other_person_id'], ['people.id'], name=op.f('fk_possible_duplicate_people_other_person_id_people'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], name=op.f('fk_possible_duplicate_people_person_id_people'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_possible_duplicate_people')),
    sa.UniqueConstraint('person_id', 'other_person_id', name='uq_possible_duplicate_people_pair')
    )
    op.create_index(op.f('ix_possible_duplicate_people_company_id'), 'possible_duplicate_people', ['company_id'], unique=False)
    op.create_index(op.f('ix_possible_duplicate_people_person_id'), 'possible_duplicate_people', ['person_id'], unique=False)
    op.add_column('companies', sa.Column('people_status', sa.String(length=16), server_default='not_started', nullable=False))
    op.add_column('companies', sa.Column('people_message', sa.String(length=300), nullable=True))
    op.add_column('companies', sa.Column('people_researched_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('companies', sa.Column('people_version', sa.SmallInteger(), nullable=True))
    op.add_column('companies', sa.Column('people_coverage', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('company_people', sa.Column('employment_status', sa.String(length=10), server_default='current', nullable=False))
    op.add_column('company_people', sa.Column('title_rank', sa.SmallInteger(), nullable=True))
    op.add_column('company_people', sa.Column('confidence_components', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('company_people', sa.Column('corrected_fields', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('company_people', sa.Column('corrected_by_user_id', sa.Integer(), nullable=True))
    op.add_column('company_people', sa.Column('corrected_at', sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(op.f('fk_company_people_corrected_by_user_id_users'), 'company_people', 'users', ['corrected_by_user_id'], ['id'], ondelete='SET NULL')
    op.add_column('people', sa.Column('profile_url', sa.String(length=500), nullable=True))
    op.execute("UPDATE company_people SET employment_status = 'former' WHERE NOT is_current")
    op.create_check_constraint(op.f('ck_company_people_employment_status_valid'), 'company_people',
                               "employment_status IN ('current', 'former', 'unknown')")
    op.create_check_constraint(op.f('ck_company_people_is_current_matches_status'), 'company_people',
                               "is_current = (employment_status = 'current')")
    op.create_check_constraint(op.f('ck_companies_people_status_valid'), 'companies',
                               "people_status IN ('not_started', 'queued', 'researching', 'partial', 'completed', "
                               "'failed')")


def downgrade() -> None:
    op.drop_constraint(op.f('ck_companies_people_status_valid'), 'companies', type_='check')
    op.drop_constraint(op.f('ck_company_people_is_current_matches_status'), 'company_people', type_='check')
    op.drop_constraint(op.f('ck_company_people_employment_status_valid'), 'company_people', type_='check')
    op.drop_column('people', 'profile_url')
    op.drop_constraint(op.f('fk_company_people_corrected_by_user_id_users'), 'company_people', type_='foreignkey')
    op.drop_column('company_people', 'corrected_at')
    op.drop_column('company_people', 'corrected_by_user_id')
    op.drop_column('company_people', 'corrected_fields')
    op.drop_column('company_people', 'confidence_components')
    op.drop_column('company_people', 'title_rank')
    op.drop_column('company_people', 'employment_status')
    op.drop_column('companies', 'people_coverage')
    op.drop_column('companies', 'people_version')
    op.drop_column('companies', 'people_researched_at')
    op.drop_column('companies', 'people_message')
    op.drop_column('companies', 'people_status')
    op.drop_index(op.f('ix_possible_duplicate_people_person_id'), table_name='possible_duplicate_people')
    op.drop_index(op.f('ix_possible_duplicate_people_company_id'), table_name='possible_duplicate_people')
    op.drop_table('possible_duplicate_people')
