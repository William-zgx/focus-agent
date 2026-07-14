from __future__ import annotations

from alembic import op

from focus_agent.repositories.postgres_schema import _run_migration_v19

revision = "20260713_agent_team_v2_schema"
down_revision = "add_memory_embedding_status"
branch_labels = None
depends_on = None

_AGENT_TEAM_V2_TABLES = (
    "focus_agent_team_events",
    "focus_agent_team_evidence",
    "focus_agent_team_side_effect_receipts",
    "focus_agent_team_resource_leases",
    "focus_agent_team_jobs",
    "focus_agent_team_approvals",
    "focus_agent_team_checkpoints",
    "focus_agent_team_task_attempts",
    "focus_agent_team_task_edges",
    "focus_agent_team_revisions",
)


def upgrade() -> None:
    _run_migration_v19(op.execute)


def downgrade() -> None:
    for table in _AGENT_TEAM_V2_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table}")
