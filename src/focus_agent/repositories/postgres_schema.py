from __future__ import annotations

from collections.abc import Callable

import psycopg


SCHEMA_VERSION = 7


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


def _run_migration_v3(execute: Callable[..., object]) -> None:
    execute(
        """
        CREATE TABLE IF NOT EXISTS focus_users (
            user_id TEXT PRIMARY KEY,
            display_name TEXT,
            email TEXT,
            tenant_id TEXT,
            status TEXT NOT NULL,
            roles_json JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            last_seen_at TIMESTAMPTZ,
            data_json JSONB NOT NULL
        )
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS focus_admin_audit_events (
            event_id TEXT PRIMARY KEY,
            actor_user_id TEXT,
            tenant_id TEXT,
            action TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            resource_id TEXT,
            decision TEXT NOT NULL,
            reason TEXT,
            request_id TEXT,
            created_at TIMESTAMPTZ NOT NULL,
            data_json JSONB NOT NULL
        )
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_users_tenant_status
        ON focus_users(tenant_id, status)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_users_status_created
        ON focus_users(status, created_at DESC)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_users_email
        ON focus_users(email)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_users_roles
        ON focus_users USING GIN (roles_json)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_admin_audit_actor_created
        ON focus_admin_audit_events(actor_user_id, created_at DESC)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_admin_audit_resource_created
        ON focus_admin_audit_events(resource_type, resource_id, created_at DESC)
        """
    )


def _run_migration_v4(execute: Callable[..., object]) -> None:
    execute("ALTER TABLE focus_users ADD COLUMN IF NOT EXISTS username TEXT")
    execute("ALTER TABLE focus_users ADD COLUMN IF NOT EXISTS password_hash TEXT")
    execute(
        "ALTER TABLE focus_users ADD COLUMN IF NOT EXISTS auth_provider TEXT NOT NULL DEFAULT 'local'"
    )
    execute("ALTER TABLE focus_users ADD COLUMN IF NOT EXISTS external_subject TEXT")
    execute(
        "ALTER TABLE focus_users ADD COLUMN IF NOT EXISTS failed_login_count INT NOT NULL DEFAULT 0"
    )
    execute("ALTER TABLE focus_users ADD COLUMN IF NOT EXISTS locked_until TIMESTAMPTZ")
    execute("ALTER TABLE focus_users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ")
    execute("ALTER TABLE focus_users ADD COLUMN IF NOT EXISTS password_updated_at TIMESTAMPTZ")
    execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_focus_users_username
        ON focus_users(LOWER(username))
        WHERE username IS NOT NULL
        """
    )
    execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_focus_users_external_subject
        ON focus_users(auth_provider, external_subject)
        WHERE external_subject IS NOT NULL
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS focus_user_sessions (
            session_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES focus_users(user_id) ON DELETE CASCADE,
            refresh_token_hash TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ,
            last_seen_at TIMESTAMPTZ,
            data_json JSONB NOT NULL
        )
        """
    )
    execute(
        "ALTER TABLE focus_user_sessions ADD COLUMN IF NOT EXISTS refresh_token_hash TEXT NOT NULL DEFAULT ''"
    )
    execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_focus_user_sessions_refresh_token_hash
        ON focus_user_sessions(refresh_token_hash)
        WHERE refresh_token_hash <> ''
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_user_sessions_user_created
        ON focus_user_sessions(user_id, created_at DESC)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_user_sessions_user_revoked
        ON focus_user_sessions(user_id, revoked_at)
        """
    )


def _run_migration_v5(execute: Callable[..., object]) -> None:
    execute(
        """
        CREATE TABLE IF NOT EXISTS focus_runtime_locks (
            lock_key TEXT PRIMARY KEY,
            lock_type TEXT NOT NULL,
            owner TEXT NOT NULL,
            acquired_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_runtime_locks_type_expires
        ON focus_runtime_locks(lock_type, expires_at)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_runtime_locks_owner
        ON focus_runtime_locks(owner)
        """
    )


def _run_migration_v6(execute: Callable[..., object]) -> None:
    execute(
        """
        CREATE TABLE IF NOT EXISTS focus_background_jobs (
            job_key TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            attempt INT NOT NULL DEFAULT 0,
            claimed_by TEXT,
            claimed_until TIMESTAMPTZ,
            last_error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_background_jobs_status_updated
        ON focus_background_jobs(status, updated_at DESC)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_background_jobs_claimed_until
        ON focus_background_jobs(claimed_until)
        """
    )


def _run_migration_v7(execute: Callable[..., object]) -> None:
    execute("ALTER TABLE focus_background_jobs ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'legacy'")
    execute("ALTER TABLE focus_background_jobs ADD COLUMN IF NOT EXISTS payload JSONB NOT NULL DEFAULT '{}'::jsonb")
    execute("ALTER TABLE focus_background_jobs ADD COLUMN IF NOT EXISTS run_at TIMESTAMPTZ NOT NULL DEFAULT now()")
    execute("ALTER TABLE focus_background_jobs ADD COLUMN IF NOT EXISTS max_attempts INT NOT NULL DEFAULT 1")
    execute("ALTER TABLE focus_background_jobs ADD COLUMN IF NOT EXISTS dedupe_policy TEXT NOT NULL DEFAULT 'skip'")
    execute("ALTER TABLE focus_background_jobs ADD COLUMN IF NOT EXISTS claim_token TEXT")
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_background_jobs_due
        ON focus_background_jobs(status, run_at ASC, updated_at ASC)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_background_jobs_claim_token
        ON focus_background_jobs(claim_token)
        """
    )


_MIGRATIONS: tuple[tuple[int, Callable[[Callable[..., object]], None]], ...] = (
    (1, _run_migration_v1),
    (2, _run_migration_v2),
    (3, _run_migration_v3),
    (4, _run_migration_v4),
    (5, _run_migration_v5),
    (6, _run_migration_v6),
    (7, _run_migration_v7),
)
