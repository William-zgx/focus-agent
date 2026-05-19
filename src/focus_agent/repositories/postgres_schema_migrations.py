from __future__ import annotations

from collections.abc import Callable


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
    execute(
        "ALTER TABLE focus_background_jobs ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'legacy'"
    )
    execute(
        "ALTER TABLE focus_background_jobs ADD COLUMN IF NOT EXISTS payload JSONB NOT NULL DEFAULT '{}'::jsonb"
    )
    execute(
        "ALTER TABLE focus_background_jobs ADD COLUMN IF NOT EXISTS run_at TIMESTAMPTZ NOT NULL DEFAULT now()"
    )
    execute(
        "ALTER TABLE focus_background_jobs ADD COLUMN IF NOT EXISTS max_attempts INT NOT NULL DEFAULT 1"
    )
    execute(
        "ALTER TABLE focus_background_jobs ADD COLUMN IF NOT EXISTS dedupe_policy TEXT NOT NULL DEFAULT 'skip'"
    )
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
            embedding_status TEXT NOT NULL DEFAULT 'pending',
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
        CREATE INDEX IF NOT EXISTS idx_focus_memories_embedding_status_updated
        ON focus_memories(embedding_status, updated_at DESC)
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


def _run_migration_v11(execute: Callable[..., object]) -> None:
    execute(
        """
        CREATE TABLE IF NOT EXISTS focus_harness_runs (
            run_id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            assistant_id TEXT,
            user_id TEXT,
            status TEXT NOT NULL,
            on_disconnect TEXT NOT NULL DEFAULT 'cancel',
            multitask_strategy TEXT NOT NULL,
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            kwargs_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            completion_json JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS focus_harness_run_events (
            event_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES focus_harness_runs(run_id) ON DELETE CASCADE,
            event TEXT NOT NULL,
            data_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            sequence INT NOT NULL,
            stream_event_id TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (run_id, sequence)
        )
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS focus_harness_tool_events (
            event_id TEXT PRIMARY KEY
                REFERENCES focus_harness_run_events(event_id) ON DELETE CASCADE,
            run_id TEXT NOT NULL REFERENCES focus_harness_runs(run_id) ON DELETE CASCADE,
            tool_call_id TEXT,
            tool_name TEXT,
            status TEXT NOT NULL,
            sequence INT NOT NULL,
            args_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            result_json JSONB,
            error TEXT,
            duration_ms DOUBLE PRECISION,
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_harness_runs_thread_created
        ON focus_harness_runs(thread_id, created_at DESC)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_harness_runs_status_updated
        ON focus_harness_runs(status, updated_at DESC)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_harness_run_events_run_sequence
        ON focus_harness_run_events(run_id, sequence)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_harness_run_events_stream_event
        ON focus_harness_run_events(stream_event_id)
        WHERE stream_event_id IS NOT NULL
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_harness_tool_events_run_sequence
        ON focus_harness_tool_events(run_id, sequence)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_harness_tool_events_tool_name
        ON focus_harness_tool_events(tool_name, created_at DESC)
        WHERE tool_name IS NOT NULL
        """
    )


def _run_migration_v12(execute: Callable[..., object]) -> None:
    execute(
        "ALTER TABLE focus_background_jobs ADD COLUMN IF NOT EXISTS last_heartbeat_at TIMESTAMPTZ"
    )
    execute("ALTER TABLE focus_background_jobs ADD COLUMN IF NOT EXISTS last_failed_at TIMESTAMPTZ")
    execute(
        "ALTER TABLE focus_background_jobs ADD COLUMN IF NOT EXISTS dead_lettered_at TIMESTAMPTZ"
    )
    execute("ALTER TABLE focus_background_jobs ADD COLUMN IF NOT EXISTS idempotency_key TEXT")
    execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_focus_background_jobs_idempotency
        ON focus_background_jobs(idempotency_key)
        WHERE idempotency_key IS NOT NULL
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS focus_background_jobs_dead_letter (
            job_key TEXT PRIMARY KEY,
            original_payload JSONB NOT NULL,
            last_error TEXT,
            attempts INT NOT NULL,
            moved_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_background_jobs_retry_due
        ON focus_background_jobs(status, run_at ASC, updated_at ASC)
        WHERE status IN ('pending', 'retrying')
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_background_jobs_dead_lettered
        ON focus_background_jobs(dead_lettered_at DESC)
        WHERE status = 'dead_lettered'
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_background_jobs_running_heartbeat
        ON focus_background_jobs(last_heartbeat_at)
        WHERE status = 'running'
        """
    )


def _run_migration_v13(execute: Callable[..., object]) -> None:
    execute(
        """
        CREATE TABLE IF NOT EXISTS focus_notes (
            note_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT '',
            tags TEXT[] NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'active',
            source_thread_id TEXT,
            source_artifact_id TEXT,
            is_archived BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            archived_at TIMESTAMPTZ,
            data_json JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS focus_tasks (
            task_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'todo',
            due_at TIMESTAMPTZ,
            priority INT,
            source_thread_id TEXT,
            source_note_id TEXT REFERENCES focus_notes(note_id) ON DELETE SET NULL,
            assignee_user_id TEXT,
            tags TEXT[] NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at TIMESTAMPTZ,
            archived_at TIMESTAMPTZ,
            data_json JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS focus_task_events (
            event_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES focus_tasks(task_id) ON DELETE CASCADE,
            user_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            data_json JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_notes_user_updated
        ON focus_notes(user_id, is_archived, updated_at DESC)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_notes_tags
        ON focus_notes USING GIN(tags)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_tasks_user_status_updated
        ON focus_tasks(user_id, status, updated_at DESC)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_task_events_task_created
        ON focus_task_events(task_id, created_at)
        """
    )


def _run_migration_v14(execute: Callable[..., object]) -> None:
    for table in ("focus_notes", "focus_tasks"):
        execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS source_kind TEXT")
        execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS source_id TEXT")
        execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS source_url TEXT")
        execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS pinned_context JSONB NOT NULL DEFAULT '{{}}'::jsonb"
        )
        execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS captured_from TEXT")
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_notes_source
        ON focus_notes(user_id, source_kind, source_id)
        WHERE source_kind IS NOT NULL OR source_id IS NOT NULL
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_tasks_source
        ON focus_tasks(user_id, source_kind, source_id)
        WHERE source_kind IS NOT NULL OR source_id IS NOT NULL
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS focus_agent_team_merge_reviews (
            review_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            user_id TEXT,
            status TEXT NOT NULL DEFAULT 'draft',
            selected_task_ids TEXT[] NOT NULL DEFAULT '{}',
            excluded_task_ids TEXT[] NOT NULL DEFAULT '{}',
            changed_files TEXT[] NOT NULL DEFAULT '{}',
            conflict_files TEXT[] NOT NULL DEFAULT '{}',
            preview_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            apply_result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            data_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            applied_at TIMESTAMPTZ,
            rejected_at TIMESTAMPTZ
        )
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS focus_agent_team_merge_review_events (
            event_id TEXT PRIMARY KEY,
            review_id TEXT NOT NULL REFERENCES focus_agent_team_merge_reviews(review_id) ON DELETE CASCADE,
            session_id TEXT NOT NULL,
            user_id TEXT,
            kind TEXT NOT NULL DEFAULT 'updated',
            data_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_agent_team_merge_reviews_session
        ON focus_agent_team_merge_reviews(session_id, updated_at DESC)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_agent_team_merge_review_events_review
        ON focus_agent_team_merge_review_events(review_id, created_at)
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS focus_feedback_events (
            event_id TEXT PRIMARY KEY,
            user_id TEXT,
            source_kind TEXT NOT NULL,
            source_id TEXT,
            sentiment TEXT,
            category TEXT,
            data_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_feedback_events_source
        ON focus_feedback_events(source_kind, source_id, created_at DESC)
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS focus_context_memory_evidence (
            evidence_id TEXT PRIMARY KEY,
            user_id TEXT,
            thread_id TEXT,
            turn_id TEXT,
            source_kind TEXT NOT NULL DEFAULT 'context_explain',
            selected_memories JSONB NOT NULL DEFAULT '[]'::jsonb,
            excluded_memories JSONB NOT NULL DEFAULT '[]'::jsonb,
            compaction_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
            drift_report JSONB NOT NULL DEFAULT '{}'::jsonb,
            artifact_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
            token_counting JSONB NOT NULL DEFAULT '{}'::jsonb,
            risk_flags TEXT[] NOT NULL DEFAULT '{}',
            data_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_context_memory_evidence_thread
        ON focus_context_memory_evidence(thread_id, created_at DESC)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_context_memory_evidence_turn
        ON focus_context_memory_evidence(turn_id, created_at DESC)
        WHERE turn_id IS NOT NULL
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS focus_skill_selection_events (
            selection_id TEXT PRIMARY KEY,
            user_id TEXT,
            message_hash TEXT,
            selection_source TEXT NOT NULL DEFAULT 'none',
            explicit_hints TEXT[] NOT NULL DEFAULT '{}',
            activated_skill_ids TEXT[] NOT NULL DEFAULT '{}',
            semantic_candidates JSONB NOT NULL DEFAULT '[]'::jsonb,
            confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
            feedback TEXT,
            user_override JSONB NOT NULL DEFAULT '{}'::jsonb,
            data_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS focus_skill_preferences (
            preference_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            skill_id TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'default',
            data_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(user_id, skill_id)
        )
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_skill_selection_events_user
        ON focus_skill_selection_events(user_id, created_at DESC)
        """
    )


def _run_migration_v15(execute: Callable[..., object]) -> None:
    execute(
        """
        CREATE TABLE IF NOT EXISTS agent_resource_claims (
            claim_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            resource_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            lock_mode TEXT NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            released BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_agent_resource_claims_active
        ON agent_resource_claims (session_id, resource_id)
        WHERE released = FALSE
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS agent_messages (
            message_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            source_agent TEXT NOT NULL,
            target_agent TEXT,
            message_type TEXT NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ,
            acked_at TIMESTAMPTZ
        )
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_agent_messages_unacked
        ON agent_messages (session_id, target_agent, created_at)
        WHERE acked_at IS NULL
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS tool_approval_requests (
            request_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            tool_args JSONB NOT NULL DEFAULT '{}'::jsonb,
            risk_level TEXT NOT NULL,
            status TEXT NOT NULL,
            timeout_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            decided_by TEXT
        )
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tool_approval_requests_session_status
        ON tool_approval_requests (session_id, status)
        """
    )


def _run_migration_v16(execute: Callable[..., object]) -> None:
    execute(
        """
        CREATE TABLE IF NOT EXISTS focus_rate_limit_buckets (
            bucket_key TEXT PRIMARY KEY,
            token_count INT NOT NULL DEFAULT 0,
            window_start TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_rate_limit_buckets_updated_at
        ON focus_rate_limit_buckets (updated_at)
        """
    )


def _run_migration_v17(execute: Callable[..., object]) -> None:
    execute(
        """
        CREATE TABLE IF NOT EXISTS focus_branch_decision_events (
            decision_id TEXT PRIMARY KEY,
            user_id TEXT,
            root_thread_id TEXT NOT NULL,
            source_thread_id TEXT NOT NULL,
            branch_id TEXT,
            action TEXT NOT NULL,
            status TEXT NOT NULL,
            mode TEXT NOT NULL,
            score DOUBLE PRECISION NOT NULL DEFAULT 0,
            threshold DOUBLE PRECISION NOT NULL DEFAULT 0,
            signals JSONB NOT NULL DEFAULT '[]'::jsonb,
            rationale TEXT NOT NULL DEFAULT '',
            request_id TEXT,
            trace_id TEXT,
            idempotency_key TEXT,
            promoted_action_id TEXT,
            dismiss_reason TEXT,
            error TEXT,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            data_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            executed_at TIMESTAMPTZ
        )
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_branch_decision_events_user_thread
        ON focus_branch_decision_events(user_id, root_thread_id, source_thread_id, created_at DESC)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_branch_decision_events_thread_status
        ON focus_branch_decision_events(source_thread_id, status, created_at DESC)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_branch_decision_events_action
        ON focus_branch_decision_events(action, created_at DESC)
        """
    )
    execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_focus_branch_decision_events_idempotency
        ON focus_branch_decision_events(idempotency_key)
        WHERE idempotency_key IS NOT NULL
        """
    )


def _run_migration_v18(execute: Callable[..., object]) -> None:
    execute(
        """
        ALTER TABLE focus_memories
        ADD COLUMN IF NOT EXISTS embedding_status TEXT NOT NULL DEFAULT 'pending'
        """
    )
    execute(
        """
        UPDATE focus_memories
        SET embedding_status = CASE
            WHEN data_json->>'embedding_status' IN ('pending', 'ready', 'failed')
                THEN data_json->>'embedding_status'
            ELSE 'pending'
        END
        """
    )
    execute(
        """
        UPDATE focus_memories
        SET data_json = jsonb_set(
            data_json,
            '{embedding_status}',
            to_jsonb(embedding_status),
            true
        )
        WHERE data_json->>'embedding_status' IS DISTINCT FROM embedding_status
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_memories_embedding_status_updated
        ON focus_memories(embedding_status, updated_at DESC)
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
    (11, _run_migration_v11),
    (12, _run_migration_v12),
    (13, _run_migration_v13),
    (14, _run_migration_v14),
    (15, _run_migration_v15),
    (16, _run_migration_v16),
    (17, _run_migration_v17),
    (18, _run_migration_v18),
)
