from __future__ import annotations

from collections.abc import Callable

import psycopg


SCHEMA_VERSION = 2


def ensure_app_postgres_schema(database_uri: str) -> None:
    with psycopg.connect(database_uri) as conn:
        ensure_app_postgres_schema_on_connection(conn)


def ensure_app_postgres_schema_on_connection(conn: object) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS focus_schema_migrations (
                version INT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        for version, migration in _MIGRATIONS:
            cur.execute("SELECT version FROM focus_schema_migrations WHERE version = %s", (version,))
            existing = cur.fetchone()
            if existing is not None:
                continue
            migration(cur.execute)
            cur.execute(
                "INSERT INTO focus_schema_migrations (version) VALUES (%s) ON CONFLICT (version) DO NOTHING",
                (version,),
            )


def _run_migration_v1(execute: Callable[..., object]) -> None:
    execute(
        """
        CREATE TABLE IF NOT EXISTS focus_conversations (
            root_thread_id TEXT PRIMARY KEY,
            owner_user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            title_pending_ai BOOLEAN NOT NULL DEFAULT false,
            is_archived BOOLEAN NOT NULL DEFAULT false,
            archived_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS focus_thread_access (
            thread_id TEXT PRIMARY KEY,
            root_thread_id TEXT NOT NULL,
            owner_user_id TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS focus_branches (
            branch_id TEXT PRIMARY KEY,
            root_thread_id TEXT NOT NULL,
            parent_thread_id TEXT NOT NULL,
            child_thread_id TEXT NOT NULL UNIQUE,
            return_thread_id TEXT NOT NULL,
            owner_user_id TEXT NOT NULL,
            branch_name TEXT NOT NULL,
            branch_role TEXT NOT NULL,
            branch_depth INT NOT NULL,
            branch_status TEXT NOT NULL,
            is_archived BOOLEAN NOT NULL DEFAULT false,
            archived_at TIMESTAMPTZ,
            fork_checkpoint_id TEXT,
            fork_strategy TEXT NOT NULL,
            merge_proposal JSONB,
            merge_decision JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS focus_artifacts (
            artifact_id UUID PRIMARY KEY,
            title TEXT NOT NULL,
            kind TEXT NOT NULL,
            uri TEXT,
            relative_path TEXT NOT NULL,
            root_thread_id TEXT,
            source_thread_id TEXT,
            source_branch_id TEXT,
            summary TEXT,
            size_bytes BIGINT NOT NULL DEFAULT 0,
            checksum TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_focus_artifacts_relative_path
        ON focus_artifacts(relative_path)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_thread_access_root_thread
        ON focus_thread_access(root_thread_id)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_thread_access_owner_created
        ON focus_thread_access(owner_user_id, created_at DESC)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_conversations_owner_created
        ON focus_conversations(owner_user_id, created_at DESC)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_branches_root_thread
        ON focus_branches(root_thread_id)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_branches_parent_thread
        ON focus_branches(parent_thread_id)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_branches_child_thread
        ON focus_branches(child_thread_id)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_artifacts_root_thread
        ON focus_artifacts(root_thread_id)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_artifacts_source_thread
        ON focus_artifacts(source_thread_id)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_artifacts_source_branch
        ON focus_artifacts(source_branch_id)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_artifacts_updated_at
        ON focus_artifacts(updated_at DESC)
        """
    )


def _run_migration_v2(execute: Callable[..., object]) -> None:
    execute(
        """
        CREATE TABLE IF NOT EXISTS focus_agent_team_sessions (
            session_id TEXT PRIMARY KEY,
            root_thread_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            data_json JSONB NOT NULL
        )
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS focus_agent_team_tasks (
            task_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            data_json JSONB NOT NULL,
            FOREIGN KEY(session_id) REFERENCES focus_agent_team_sessions(session_id)
        )
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS focus_agent_team_outputs (
            output_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            data_json JSONB NOT NULL,
            FOREIGN KEY(task_id) REFERENCES focus_agent_team_tasks(task_id)
        )
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_agent_team_sessions_user_created
        ON focus_agent_team_sessions(user_id, created_at DESC)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_agent_team_sessions_root_created
        ON focus_agent_team_sessions(root_thread_id, created_at DESC)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_agent_team_tasks_session_created
        ON focus_agent_team_tasks(session_id, created_at)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_agent_team_outputs_task_created
        ON focus_agent_team_outputs(task_id, created_at)
        """
    )


_MIGRATIONS: tuple[tuple[int, Callable[[Callable[..., object]], None]], ...] = (
    (1, _run_migration_v1),
    (2, _run_migration_v2),
)
