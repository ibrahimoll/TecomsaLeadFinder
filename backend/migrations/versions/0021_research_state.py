"""People research state: at most one ACTIVE (queued or running) research run per company and kind, and a
'timed_out' research status (a stage stopped at its deadline: finished, never left "researching").

Duplicate active runs (two opens racing a worker claim) are failed first, keeping the oldest running one.

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-07
"""
from typing import Sequence, Union

from alembic import op

revision: str = '0021'
down_revision: Union[str, None] = '0020'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = ("enrichment_status", "people_status", "external_people_status")
_OLD = "'not_started', 'queued', 'researching', 'partial', 'completed', 'failed'"
_NEW = _OLD + ", 'timed_out'"


def _statuses(values: str) -> None:
    for column in _COLUMNS:
        op.drop_constraint(op.f(f'ck_companies_{column}_valid'), 'companies', type_='check')
        op.create_check_constraint(op.f(f'ck_companies_{column}_valid'), 'companies', f"{column} IN ({values})")


def upgrade() -> None:
    op.execute("""
        UPDATE research_runs r SET status = 'failed', completed_at = now(),
               error_message = 'Duplicate of an active run for the same company (superseded).'
        FROM (SELECT id, row_number() OVER (PARTITION BY company_id, research_type
                                            ORDER BY (status = 'running') DESC, started_at NULLS LAST, id) AS n
              FROM research_runs WHERE status IN ('queued', 'running') AND company_id IS NOT NULL) d
        WHERE r.id = d.id AND d.n > 1""")
    op.drop_index('uq_research_runs_queued_company', table_name='research_runs')
    op.create_index('uq_research_runs_active_company', 'research_runs', ['company_id', 'research_type'], unique=True,
                    postgresql_where="status IN ('queued', 'running') AND company_id IS NOT NULL")
    _statuses(_NEW)


def downgrade() -> None:
    for column in _COLUMNS:
        op.execute(f"UPDATE companies SET {column} = 'partial' WHERE {column} = 'timed_out'")
    _statuses(_OLD)
    op.drop_index('uq_research_runs_active_company', table_name='research_runs')
    op.create_index('uq_research_runs_queued_company', 'research_runs', ['company_id', 'research_type'], unique=True,
                    postgresql_where="status = 'queued' AND company_id IS NOT NULL")
