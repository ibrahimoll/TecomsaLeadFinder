"""Company owner: the lead generator who found the company first (Find Leads, a lookup, a directory import, typed
in). Salespeople see only the companies they own; managers and admins see all and can reassign. Backfilled from the
creator.

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0032'
down_revision: Union[str, None] = '0031'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF NOT EXISTS: live received this DDL ahead of 0031 (the running code needed the column); re-running is a no-op
    op.execute(UPGRADE)


UPGRADE = """
ALTER TABLE companies ADD COLUMN IF NOT EXISTS owner_user_id INTEGER;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_companies_owner_user_id_users') THEN
    ALTER TABLE companies ADD CONSTRAINT fk_companies_owner_user_id_users FOREIGN KEY (owner_user_id)
      REFERENCES users (id) ON DELETE SET NULL;
    UPDATE companies SET owner_user_id = created_by_user_id;
  END IF;
END $$;
CREATE INDEX IF NOT EXISTS ix_companies_owner_user_id ON companies (owner_user_id);
"""


def downgrade() -> None:
    op.drop_index("ix_companies_owner_user_id", table_name="companies")
    op.drop_constraint("fk_companies_owner_user_id_users", "companies", type_="foreignkey")
    op.drop_column("companies", "owner_user_id")
