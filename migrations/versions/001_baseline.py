from __future__ import annotations

from alembic import op

from focus_agent.repositories.postgres_schema import (
    app_postgres_schema_baseline_statements,
    app_postgres_schema_baseline_tables,
)

revision = "001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in app_postgres_schema_baseline_statements():
        op.execute(statement)


def downgrade() -> None:
    for table in reversed(app_postgres_schema_baseline_tables()):
        op.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
