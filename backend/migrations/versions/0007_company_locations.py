"""Company locations: branch consolidation

company_sources rows become the company's locations (name, address, city, coordinates,
phone; a second listing of the same place points to it with same_place_as_id). Discovery
results carry the locations a search found for each company; runs count branches and
unique companies separately from duplicate listings.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0007'
down_revision: Union[str, None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('company_sources', sa.Column('name', sa.String(length=255), nullable=True))
    op.add_column('company_sources', sa.Column('address', sa.String(length=500), nullable=True))
    op.add_column('company_sources', sa.Column('city', sa.String(length=100), nullable=True))
    op.add_column('company_sources', sa.Column('latitude', sa.Float(), nullable=True))
    op.add_column('company_sources', sa.Column('longitude', sa.Float(), nullable=True))
    op.add_column('company_sources', sa.Column('phone', sa.String(length=50), nullable=True))
    op.add_column('company_sources', sa.Column('same_place_as_id', sa.Integer(), nullable=True))
    op.create_foreign_key(op.f('fk_company_sources_same_place_as_id_company_sources'), 'company_sources',
                          'company_sources', ['same_place_as_id'], ['id'], ondelete='SET NULL')
    # Existing records: each is its own location, described by what the source said.
    op.execute("""
        UPDATE company_sources SET
            name = left(data->>'name', 255),
            address = left(data->'location'->>'address', 500),
            city = left(data->'location'->>'city', 100),
            latitude = (data->'location'->>'latitude')::float,
            longitude = (data->'location'->>'longitude')::float,
            phone = left(coalesce(data->'phones'->>0, data->'tags'->>'phone'), 50)
    """)
    for column in ('locations', 'sources'):
        op.add_column('discovery_results', sa.Column(column, postgresql.JSONB(astext_type=sa.Text()),
                                                     server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column('discovery_runs', sa.Column('branch_count', sa.Integer(), server_default='0', nullable=False))
    op.add_column('discovery_runs', sa.Column('company_count', sa.Integer(), server_default='0', nullable=False))
    op.execute("""
        UPDATE discovery_runs r SET
            branch_count = b.n,
            duplicate_count = r.duplicate_count - b.n
        FROM (SELECT run_id, count(*) AS n FROM discovery_results WHERE state = 'MERGED_BRANCH' GROUP BY run_id) b
        WHERE b.run_id = r.id
    """)


def downgrade() -> None:
    op.execute("UPDATE discovery_runs SET duplicate_count = duplicate_count + branch_count")
    op.drop_column('discovery_runs', 'company_count')
    op.drop_column('discovery_runs', 'branch_count')
    op.drop_column('discovery_results', 'sources')
    op.drop_column('discovery_results', 'locations')
    op.drop_constraint(op.f('fk_company_sources_same_place_as_id_company_sources'), 'company_sources',
                       type_='foreignkey')
    for column in ('same_place_as_id', 'phone', 'longitude', 'latitude', 'city', 'address', 'name'):
        op.drop_column('company_sources', column)
