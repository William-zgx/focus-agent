from __future__ import annotations

from collections.abc import Callable

import psycopg


SCHEMA_VERSION = 10


def ensure_app_postgres_schema(
    database_uri: str,
    *,
    dimensions: int = 1536,
    vector_index: bool = False,
    memory_embeddings_enabled: bool = False,
    pgvector_extension_mode: str = "auto_create",
) -> None:
    with psycopg.connect(database_uri) as conn:
        ensure_app_postgres_schema_on_connection(
            conn,
            dimensions=dimensions,
            vector_index=vector_index,
            memory_embeddings_enabled=memory_embeddings_enabled,
            pgvector_extension_mode=pgvector_extension_mode,
        )


def ensure_app_postgres_schema_on_connection(
    conn: object,
    *,
    dimensions: int = 1536,
    vector_index: bool = False,
    memory_embeddings_enabled: bool = False,
    pgvector_extension_mode: str = "auto_create",
) -> None:
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
            if version == 10 and not memory_embeddings_enabled:
                continue
            cur.execute("SELECT version FROM focus_schema_migrations WHERE version = %s", (version,))
            existing = cur.fetchone()
            if existing is not None:
                continue
            if version == 10:
                _run_migration_v10(
                    cur.execute,
                    dimensions=dimensions,
                    vector_index=vector_index,
                    pgvector_extension_mode=pgvector_extension_mode,
                )
            else:
                migration(cur.execute)
            cur.execute(
                "INSERT INTO focus_schema_migrations (version) VALUES (%s) ON CONFLICT (version) DO NOTHING",
                (version,),
            )


def rebuild_memory_embedding_index(
    database_uri: str,
    *,
    dimensions: int = 1536,
    vector_index: bool = False,
    pgvector_extension_mode: str = "auto_create",
) -> None:
    with psycopg.connect(database_uri) as conn:
        rebuild_memory_embedding_index_on_connection(
            conn,
            dimensions=dimensions,
            vector_index=vector_index,
            pgvector_extension_mode=pgvector_extension_mode,
        )


def rebuild_memory_embedding_index_on_connection(
    conn: object,
    *,
    dimensions: int = 1536,
    vector_index: bool = False,
    pgvector_extension_mode: str = "auto_create",
) -> None:
    ensure_app_postgres_schema_on_connection(
        conn,
        dimensions=dimensions,
        vector_index=vector_index,
        memory_embeddings_enabled=False,
        pgvector_extension_mode=pgvector_extension_mode,
    )
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS focus_memory_embeddings CASCADE")
        _run_migration_v10(
            cur.execute,
            dimensions=dimensions,
            vector_index=vector_index,
            pgvector_extension_mode=pgvector_extension_mode,
        )
        cur.execute(
            """
            INSERT INTO focus_schema_migrations (version)
            VALUES (10)
            ON CONFLICT (version) DO NOTHING
            """
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


def _run_migration_v8(execute: Callable[..., object]) -> None:
    execute(
        """
        CREATE TABLE IF NOT EXISTS focus_memories (
            memory_id TEXT PRIMARY KEY,
            namespace TEXT[] NOT NULL,
            kind TEXT NOT NULL,
            scope TEXT NOT NULL,
            visibility TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            user_id TEXT,
            root_thread_id TEXT,
            source_thread_id TEXT,
            source_branch_id TEXT,
            semantic_key TEXT,
            fingerprint TEXT,
            confidence DOUBLE PRECISION,
            importance DOUBLE PRECISION NOT NULL DEFAULT 0.5,
            summary TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL DEFAULT '',
            promoted_to_main BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ,
            data_json JSONB NOT NULL
        )
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS focus_memory_audit_events (
            event_id TEXT PRIMARY KEY,
            action TEXT NOT NULL,
            decision TEXT NOT NULL,
            memory_id TEXT,
            candidate_id TEXT,
            actor TEXT,
            reason TEXT,
            namespace TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
            user_id TEXT,
            root_thread_id TEXT,
            source_thread_id TEXT,
            source_branch_id TEXT,
            request_id TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            data_json JSONB NOT NULL
        )
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS focus_memory_tombstones (
            tombstone_id TEXT PRIMARY KEY,
            memory_id TEXT NOT NULL UNIQUE,
            namespace TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
            semantic_key TEXT,
            fingerprint TEXT,
            actor TEXT,
            reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            data_json JSONB NOT NULL
        )
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS focus_memory_candidates (
            candidate_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            agent_id TEXT,
            task_id TEXT,
            branch_id TEXT,
            root_thread_id TEXT,
            user_id TEXT,
            evidence_refs TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            data_json JSONB NOT NULL
        )
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_memories_namespace_status_updated
        ON focus_memories(namespace, status, updated_at DESC)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_memories_kind_scope_visibility
        ON focus_memories(kind, scope, visibility)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_memories_user_updated
        ON focus_memories(user_id, updated_at DESC)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_memories_root_updated
        ON focus_memories(root_thread_id, updated_at DESC)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_memories_source_branch
        ON focus_memories(source_branch_id, updated_at DESC)
        """
    )
    execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_focus_memories_active_fingerprint
        ON focus_memories(namespace, fingerprint)
        WHERE fingerprint IS NOT NULL AND status != 'forgotten' AND deleted_at IS NULL
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_memories_semantic_key
        ON focus_memories(semantic_key)
        WHERE semantic_key IS NOT NULL
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_memories_text_search
        ON focus_memories USING GIN (
            to_tsvector('simple', coalesce(summary, '') || ' ' || coalesce(content, ''))
        )
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_memory_audit_memory_created
        ON focus_memory_audit_events(memory_id, created_at DESC)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_memory_audit_root_created
        ON focus_memory_audit_events(root_thread_id, created_at DESC)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_memory_tombstones_semantic_key
        ON focus_memory_tombstones(semantic_key)
        WHERE semantic_key IS NOT NULL
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_memory_candidates_status_updated
        ON focus_memory_candidates(status, updated_at DESC)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_memory_candidates_root_updated
        ON focus_memory_candidates(root_thread_id, updated_at DESC)
        """
    )


def _run_migration_v9(execute: Callable[..., object]) -> None:
    execute(
        """
        UPDATE focus_memories
        SET
            content = '',
            summary = '[forgotten]',
            deleted_at = COALESCE(deleted_at, updated_at, now()),
            updated_at = now(),
            data_json =
                jsonb_set(
                    jsonb_set(
                        jsonb_set(
                            jsonb_set(
                                jsonb_set(data_json, '{content}', to_jsonb(''::text), true),
                                '{summary}', to_jsonb('[forgotten]'::text), true
                            ),
                            '{status}', to_jsonb('forgotten'::text), true
                        ),
                        '{deleted_at}',
                        to_jsonb(to_char(COALESCE(deleted_at, updated_at, now()), 'YYYY-MM-DD"T"HH24:MI:SS.USOF')),
                        true
                    ),
                    '{updated_at}',
                    to_jsonb(to_char(now(), 'YYYY-MM-DD"T"HH24:MI:SS.USOF')),
                    true
                )
        WHERE status = 'forgotten'
          AND (
              content <> ''
              OR summary <> '[forgotten]'
              OR data_json->>'content' IS DISTINCT FROM ''
              OR data_json->>'summary' IS DISTINCT FROM '[forgotten]'
              OR data_json->>'status' IS DISTINCT FROM 'forgotten'
              OR deleted_at IS NULL
              OR NOT (data_json ? 'deleted_at')
              OR data_json->>'deleted_at' IS NULL
          )
        """
    )


def _run_migration_v10(
    execute: Callable[..., object],
    *,
    dimensions: int = 1536,
    vector_index: bool = False,
    pgvector_extension_mode: str = "auto_create",
) -> None:
    safe_dimensions = max(1, int(dimensions))
    mode = _normalize_pgvector_extension_mode(pgvector_extension_mode)
    if mode == "auto_create":
        execute("CREATE EXTENSION IF NOT EXISTS vector")
    else:
        execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
                    RAISE EXCEPTION
                        'pgvector extension is required before focus_memory_embeddings migration';
                END IF;
            END $$;
            """
        )
    execute(
        f"""
        CREATE TABLE IF NOT EXISTS focus_memory_embeddings (
            embedding_id TEXT PRIMARY KEY,
            memory_id TEXT NOT NULL REFERENCES focus_memories(memory_id) ON DELETE CASCADE,
            namespace TEXT[] NOT NULL,
            provider_id TEXT NOT NULL,
            model_id TEXT NOT NULL,
            dimensions INT NOT NULL,
            content_hash TEXT NOT NULL,
            embedding vector({safe_dimensions}) NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ,
            metadata_json JSONB NOT NULL DEFAULT '{{}}'::jsonb
        )
        """
    )
    execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_focus_memory_embeddings_unique_content
        ON focus_memory_embeddings(memory_id, provider_id, model_id, content_hash)
        WHERE deleted_at IS NULL
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_memory_embeddings_namespace_status_updated
        ON focus_memory_embeddings(namespace, status, updated_at DESC)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_memory_embeddings_model_status_updated
        ON focus_memory_embeddings(provider_id, model_id, status, updated_at DESC)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_memory_embeddings_content_hash
        ON focus_memory_embeddings(content_hash)
        WHERE content_hash IS NOT NULL
        """
    )
    if vector_index:
        execute(
            """
            CREATE INDEX IF NOT EXISTS idx_focus_memory_embeddings_vector
            ON focus_memory_embeddings USING hnsw (embedding vector_cosine_ops)
            WHERE status = 'active' AND deleted_at IS NULL
            """
        )


def _normalize_pgvector_extension_mode(value: object) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {"auto", "auto_create", "create", "create_if_missing"}:
        return "auto_create"
    if normalized in {"require", "required", "require_installed", "preinstalled", "pre_installed"}:
        return "required"
    raise ValueError("pgvector_extension_mode must be one of: auto_create, required")


_MIGRATIONS: tuple[tuple[int, Callable[[Callable[..., object]], None]], ...] = (
    (1, _run_migration_v1),
    (2, _run_migration_v2),
    (3, _run_migration_v3),
    (4, _run_migration_v4),
    (5, _run_migration_v5),
    (6, _run_migration_v6),
    (7, _run_migration_v7),
    (8, _run_migration_v8),
    (9, _run_migration_v9),
    (10, _run_migration_v10),
)
