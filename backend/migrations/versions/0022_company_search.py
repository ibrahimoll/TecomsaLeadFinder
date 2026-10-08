"""Direct company search: search keys on companies (GIN), alias consonant skeletons, trigram indexes for typos
(pg_trgm), and company_lookups (search analytics, negative cache, pickable public-source candidates).

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0022'
down_revision: Union[str, None] = '0021'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")  # trusted extension: the database owner may create it
    op.add_column('companies', sa.Column('search_keys', postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"),
                                         nullable=False))
    op.create_index('ix_companies_search_keys', 'companies', ['search_keys'], unique=False, postgresql_using='gin')
    op.create_index('ix_companies_normalized_name_trgm', 'companies', ['normalized_name'], unique=False,
                    postgresql_using='gin', postgresql_ops={'normalized_name': 'gin_trgm_ops'})
    op.add_column('company_aliases', sa.Column('skeleton_key', sa.String(length=300), nullable=True))
    op.create_index(op.f('ix_company_aliases_skeleton_key'), 'company_aliases', ['skeleton_key'], unique=False)
    op.create_index('ix_company_aliases_normalized_alias_trgm', 'company_aliases', ['normalized_alias'], unique=False,
                    postgresql_using='gin', postgresql_ops={'normalized_alias': 'gin_trgm_ops'})
    op.create_table(
        'company_lookups',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('query', sa.String(length=200), nullable=False),
        sa.Column('normalized_query', sa.String(length=200), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('country', sa.String(length=100), nullable=True),
        sa.Column('city', sa.String(length=120), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('result_company_id', sa.Integer(), nullable=True),
        sa.Column('match_type', sa.String(length=40), nullable=True),
        sa.Column('confidence', sa.String(length=12), nullable=True),
        sa.Column('result_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('external_used', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('company_created', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('sources', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"),
                  nullable=False),
        sa.Column('candidates', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"),
                  nullable=False),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['result_company_id'], ['companies.id'],
                                name=op.f('fk_company_lookups_result_company_id_companies'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_company_lookups_user_id_users'),
                                ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_company_lookups')),
    )
    op.create_index('ix_company_lookups_query', 'company_lookups', ['normalized_query', 'created_at'], unique=False)
    op.create_index(op.f('ix_company_lookups_user_id'), 'company_lookups', ['user_id'], unique=False)
    _backfill()


def _backfill() -> None:
    """Search keys of every existing company and alias (the same functions the application uses)."""
    from app.services.company_search import name_keys, skeleton_key

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, name, legal_name FROM companies")).all()
    for company_id, name, legal_name in rows:
        conn.execute(sa.text("UPDATE companies SET search_keys = :k WHERE id = :id"),
                     {"k": sorted(name_keys(name, legal_name)), "id": company_id})
    for alias_id, alias in conn.execute(sa.text("SELECT id, alias FROM company_aliases")).all():
        conn.execute(sa.text("UPDATE company_aliases SET skeleton_key = :k WHERE id = :id"),
                     {"k": (skeleton_key(alias) or "")[:300] or None, "id": alias_id})


def downgrade() -> None:
    op.drop_index(op.f('ix_company_lookups_user_id'), table_name='company_lookups')
    op.drop_index('ix_company_lookups_query', table_name='company_lookups')
    op.drop_table('company_lookups')
    op.drop_index('ix_company_aliases_normalized_alias_trgm', table_name='company_aliases')
    op.drop_index(op.f('ix_company_aliases_skeleton_key'), table_name='company_aliases')
    op.drop_column('company_aliases', 'skeleton_key')
    op.drop_index('ix_companies_normalized_name_trgm', table_name='companies')
    op.drop_index('ix_companies_search_keys', table_name='companies')
    op.drop_column('companies', 'search_keys')
