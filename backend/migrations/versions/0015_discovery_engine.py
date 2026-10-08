"""Discovery engine: company identifiers, possible duplicates, deletion suppressions, search progress,
job-queue index.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0015'
down_revision: Union[str, None] = '0014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('company_identifiers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('scheme', sa.String(length=60), nullable=False),
    sa.Column('value', sa.String(length=300), nullable=False),
    sa.Column('source_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_company_identifiers_company_id_companies'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], name=op.f('fk_company_identifiers_source_id_sources'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_company_identifiers')),
    sa.UniqueConstraint('scheme', 'value', name='uq_company_identifiers_scheme_value')
    )
    op.create_index(op.f('ix_company_identifiers_company_id'), 'company_identifiers', ['company_id'], unique=False)
    op.create_index(op.f('ix_company_identifiers_source_id'), 'company_identifiers', ['source_id'], unique=False)
    op.create_table('possible_duplicates',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('other_company_id', sa.Integer(), nullable=False),
    sa.Column('reason', sa.String(length=300), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='open', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('open', 'merged', 'distinct')", name=op.f('ck_possible_duplicates_status_valid')),
    sa.CheckConstraint('company_id <> other_company_id', name=op.f('ck_possible_duplicates_distinct_companies')),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_possible_duplicates_company_id_companies'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['other_company_id'], ['companies.id'], name=op.f('fk_possible_duplicates_other_company_id_companies'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_possible_duplicates')),
    sa.UniqueConstraint('company_id', 'other_company_id', name='uq_possible_duplicates_pair')
    )
    op.create_index(op.f('ix_possible_duplicates_other_company_id'), 'possible_duplicates', ['other_company_id'], unique=False)
    op.add_column('companies', sa.Column('identity_confidence', sa.String(length=8), nullable=True))
    op.create_check_constraint('identity_confidence_valid', 'companies',
                               "identity_confidence IS NULL OR identity_confidence IN ('low', 'medium', 'high')")
    op.add_column('lead_search_results', sa.Column('is_new', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('lead_searches', sa.Column('connectors_total', sa.Integer(), server_default='0', nullable=False))
    op.add_column('lead_searches', sa.Column('connectors_completed', sa.Integer(), server_default='0', nullable=False))
    op.add_column('lead_searches', sa.Column('progress', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('lead_searches', sa.Column('message', sa.String(length=500), nullable=True))
    op.create_index('ix_research_runs_queued', 'research_runs', ['created_at'], unique=False, postgresql_where=sa.text("status = 'queued'"))
    op.create_table('discovery_suppressions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('scheme', sa.String(length=60), nullable=False),
    sa.Column('value', sa.String(length=300), nullable=False),
    sa.Column('company_name', sa.String(length=300), nullable=False),
    sa.Column('deleted_by_user_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['deleted_by_user_id'], ['users.id'], name=op.f('fk_discovery_suppressions_deleted_by_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_discovery_suppressions')),
    sa.UniqueConstraint('scheme', 'value', name='uq_discovery_suppressions_scheme_value')
    )


def downgrade() -> None:
    op.drop_table('discovery_suppressions')
    op.drop_index('ix_research_runs_queued', table_name='research_runs', postgresql_where=sa.text("status = 'queued'"))
    op.drop_column('lead_searches', 'message')
    op.drop_column('lead_searches', 'progress')
    op.drop_column('lead_searches', 'connectors_completed')
    op.drop_column('lead_searches', 'connectors_total')
    op.drop_column('lead_search_results', 'is_new')
    op.drop_constraint(op.f('ck_companies_identity_confidence_valid'), 'companies', type_='check')
    op.drop_column('companies', 'identity_confidence')
    op.drop_index(op.f('ix_possible_duplicates_other_company_id'), table_name='possible_duplicates')
    op.drop_table('possible_duplicates')
    op.drop_index(op.f('ix_company_identifiers_source_id'), table_name='company_identifiers')
    op.drop_index(op.f('ix_company_identifiers_company_id'), table_name='company_identifiers')
    op.drop_table('company_identifiers')
