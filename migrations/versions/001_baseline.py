from __future__ import annotations

from alembic import op

from focus_agent.repositories.postgres_schema import ensure_app_postgres_schema_on_connection

revision = "001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    ensure_app_postgres_schema_on_connection(op.get_bind().connection)


def downgrade() -> None:
    connection = op.get_bind()
    tables = (
        "tool_approval_requests",
        "agent_messages",
        "agent_resource_claims",
        "focus_rate_limit_buckets",
        "focus_skill_preferences",
        "focus_skill_selection_events",
        "focus_background_jobs",
        "focus_runtime_locks",
        "focus_productivity_tasks",
        "focus_productivity_notes",
        "focus_user_sessions",
        "focus_users",
        "focus_memory_embeddings",
        "focus_memory_usage_events",
        "focus_memory_audit_events",
        "focus_memory_candidates",
        "focus_memory_records",
        "focus_artifact_metadata",
        "focus_trajectory_steps",
        "focus_trajectory_turns",
        "focus_branch_actions",
        "focus_branches",
        "focus_conversations",
        "focus_schema_migrations",
    )
    for table in tables:
        connection.exec_driver_sql(f"DROP TABLE IF EXISTS {table} CASCADE")
