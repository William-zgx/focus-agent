from __future__ import annotations

import re
from collections.abc import Callable

import psycopg

from .postgres_schema_migrations import _MIGRATIONS as _BASE_MIGRATIONS
from .postgres_schema_migrations import _run_migration_v10

SCHEMA_VERSION = 19
_SCHEMA_MIGRATION_LOCK_ID = 7612044473148256129
_CREATED_TABLE_PATTERN = re.compile(
    r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r'(?:"(?P<quoted>[A-Za-z_][A-Za-z0-9_]*)"|(?P<plain>[A-Za-z_][A-Za-z0-9_]*))\b',
    re.IGNORECASE,
)
_AGENT_TEAM_V2_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS focus_agent_team_revisions (
        revision_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL
            REFERENCES focus_agent_team_sessions(session_id) ON DELETE CASCADE,
        parent_revision_id TEXT
            REFERENCES focus_agent_team_revisions(revision_id) ON DELETE SET NULL,
        revision_number INT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        plan_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_by TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (session_id, revision_number),
        CHECK (revision_number > 0),
        CHECK (length(trim(status)) > 0)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS focus_agent_team_task_edges (
        edge_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL
            REFERENCES focus_agent_team_sessions(session_id) ON DELETE CASCADE,
        revision_id TEXT
            REFERENCES focus_agent_team_revisions(revision_id) ON DELETE SET NULL,
        upstream_task_id TEXT NOT NULL
            REFERENCES focus_agent_team_tasks(task_id) ON DELETE CASCADE,
        downstream_task_id TEXT NOT NULL
            REFERENCES focus_agent_team_tasks(task_id) ON DELETE CASCADE,
        edge_kind TEXT NOT NULL DEFAULT 'depends_on',
        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (upstream_task_id, downstream_task_id, edge_kind),
        CHECK (upstream_task_id <> downstream_task_id),
        CHECK (length(trim(edge_kind)) > 0)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS focus_agent_team_task_attempts (
        attempt_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL
            REFERENCES focus_agent_team_sessions(session_id) ON DELETE CASCADE,
        task_id TEXT NOT NULL
            REFERENCES focus_agent_team_tasks(task_id) ON DELETE CASCADE,
        revision_id TEXT
            REFERENCES focus_agent_team_revisions(revision_id) ON DELETE SET NULL,
        attempt_number INT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        worker_id TEXT,
        claim_token TEXT,
        input_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        last_error TEXT,
        started_at TIMESTAMPTZ,
        finished_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (task_id, attempt_number),
        CHECK (attempt_number > 0),
        CHECK (length(trim(status)) > 0),
        CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS focus_agent_team_checkpoints (
        checkpoint_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL
            REFERENCES focus_agent_team_sessions(session_id) ON DELETE CASCADE,
        task_id TEXT
            REFERENCES focus_agent_team_tasks(task_id) ON DELETE SET NULL,
        attempt_id TEXT
            REFERENCES focus_agent_team_task_attempts(attempt_id) ON DELETE SET NULL,
        revision_id TEXT
            REFERENCES focus_agent_team_revisions(revision_id) ON DELETE SET NULL,
        checkpoint_kind TEXT NOT NULL DEFAULT 'state',
        checkpoint_sequence BIGINT NOT NULL DEFAULT 0,
        state_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (session_id, task_id, checkpoint_sequence),
        CHECK (checkpoint_sequence >= 0),
        CHECK (length(trim(checkpoint_kind)) > 0)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS focus_agent_team_approvals (
        approval_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL
            REFERENCES focus_agent_team_sessions(session_id) ON DELETE CASCADE,
        task_id TEXT
            REFERENCES focus_agent_team_tasks(task_id) ON DELETE SET NULL,
        attempt_id TEXT
            REFERENCES focus_agent_team_task_attempts(attempt_id) ON DELETE SET NULL,
        approval_kind TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        requested_by TEXT,
        decided_by TEXT,
        request_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        decision_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        decided_at TIMESTAMPTZ,
        expires_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled', 'expired')),
        CHECK (length(trim(approval_kind)) > 0),
        CHECK (decided_at IS NULL OR decided_at >= requested_at)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS focus_agent_team_jobs (
        job_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL
            REFERENCES focus_agent_team_sessions(session_id) ON DELETE CASCADE,
        task_id TEXT
            REFERENCES focus_agent_team_tasks(task_id) ON DELETE SET NULL,
        attempt_id TEXT
            REFERENCES focus_agent_team_task_attempts(attempt_id) ON DELETE SET NULL,
        job_kind TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'queued',
        idempotency_key TEXT,
        payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        attempt_count INT NOT NULL DEFAULT 0,
        max_attempts INT NOT NULL DEFAULT 1,
        scheduled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        claimed_by TEXT,
        claimed_until TIMESTAMPTZ,
        completed_at TIMESTAMPTZ,
        last_error TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (session_id, idempotency_key),
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
        CHECK (length(trim(job_kind)) > 0),
        CHECK (attempt_count >= 0),
        CHECK (max_attempts > 0)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS focus_agent_team_resource_leases (
        lease_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL
            REFERENCES focus_agent_team_sessions(session_id) ON DELETE CASCADE,
        task_id TEXT
            REFERENCES focus_agent_team_tasks(task_id) ON DELETE SET NULL,
        attempt_id TEXT
            REFERENCES focus_agent_team_task_attempts(attempt_id) ON DELETE SET NULL,
        resource_key TEXT NOT NULL,
        holder_id TEXT NOT NULL,
        lease_mode TEXT NOT NULL DEFAULT 'exclusive',
        status TEXT NOT NULL DEFAULT 'active',
        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        acquired_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        expires_at TIMESTAMPTZ NOT NULL,
        released_at TIMESTAMPTZ,
        CHECK (lease_mode IN ('shared', 'exclusive')),
        CHECK (status IN ('active', 'released', 'expired')),
        CHECK (expires_at > acquired_at),
        CHECK (released_at IS NULL OR released_at >= acquired_at)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS focus_agent_team_side_effect_receipts (
        receipt_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL
            REFERENCES focus_agent_team_sessions(session_id) ON DELETE CASCADE,
        task_id TEXT
            REFERENCES focus_agent_team_tasks(task_id) ON DELETE SET NULL,
        attempt_id TEXT
            REFERENCES focus_agent_team_task_attempts(attempt_id) ON DELETE SET NULL,
        job_id TEXT
            REFERENCES focus_agent_team_jobs(job_id) ON DELETE SET NULL,
        idempotency_key TEXT NOT NULL,
        effect_kind TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        request_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        response_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        external_reference TEXT,
        error TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        completed_at TIMESTAMPTZ,
        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        UNIQUE (task_id, idempotency_key),
        CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'compensated')),
        CHECK (length(trim(effect_kind)) > 0),
        CHECK (completed_at IS NULL OR completed_at >= created_at)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS focus_agent_team_evidence (
        evidence_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL
            REFERENCES focus_agent_team_sessions(session_id) ON DELETE CASCADE,
        task_id TEXT
            REFERENCES focus_agent_team_tasks(task_id) ON DELETE SET NULL,
        attempt_id TEXT
            REFERENCES focus_agent_team_task_attempts(attempt_id) ON DELETE SET NULL,
        output_id TEXT
            REFERENCES focus_agent_team_outputs(output_id) ON DELETE SET NULL,
        evidence_kind TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'recorded',
        uri TEXT,
        content_hash TEXT,
        summary TEXT,
        evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        verification_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CHECK (status IN ('recorded', 'verified', 'rejected', 'superseded')),
        CHECK (length(trim(evidence_kind)) > 0)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS focus_agent_team_events (
        event_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL
            REFERENCES focus_agent_team_sessions(session_id) ON DELETE CASCADE,
        task_id TEXT
            REFERENCES focus_agent_team_tasks(task_id) ON DELETE SET NULL,
        attempt_id TEXT
            REFERENCES focus_agent_team_task_attempts(attempt_id) ON DELETE SET NULL,
        job_id TEXT
            REFERENCES focus_agent_team_jobs(job_id) ON DELETE SET NULL,
        event_type TEXT NOT NULL,
        sequence BIGINT NOT NULL,
        actor_id TEXT,
        payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (session_id, sequence),
        CHECK (sequence >= 0),
        CHECK (length(trim(event_type)) > 0)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_focus_agent_team_revisions_session_number
    ON focus_agent_team_revisions(session_id, revision_number DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_focus_agent_team_task_edges_downstream
    ON focus_agent_team_task_edges(downstream_task_id, created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_focus_agent_team_task_edges_session_revision
    ON focus_agent_team_task_edges(session_id, revision_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_focus_agent_team_task_attempts_task_status
    ON focus_agent_team_task_attempts(task_id, status, created_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_focus_agent_team_task_attempts_session_created
    ON focus_agent_team_task_attempts(session_id, created_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_focus_agent_team_checkpoints_task_created
    ON focus_agent_team_checkpoints(task_id, created_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_focus_agent_team_checkpoints_session_created
    ON focus_agent_team_checkpoints(session_id, created_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_focus_agent_team_approvals_session_status
    ON focus_agent_team_approvals(session_id, status, requested_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_focus_agent_team_approvals_task_status
    ON focus_agent_team_approvals(task_id, status, requested_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_focus_agent_team_jobs_due
    ON focus_agent_team_jobs(status, scheduled_at, created_at)
    WHERE status IN ('queued', 'running')
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_focus_agent_team_jobs_task_created
    ON focus_agent_team_jobs(task_id, created_at DESC)
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_focus_agent_team_resource_leases_active_exclusive
    ON focus_agent_team_resource_leases(resource_key)
    WHERE status = 'active' AND lease_mode = 'exclusive'
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_focus_agent_team_resource_leases_active_expiry
    ON focus_agent_team_resource_leases(status, expires_at)
    WHERE status = 'active'
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_focus_agent_team_side_effect_receipts_session_created
    ON focus_agent_team_side_effect_receipts(session_id, created_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_focus_agent_team_side_effect_receipts_job
    ON focus_agent_team_side_effect_receipts(job_id)
    WHERE job_id IS NOT NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_focus_agent_team_evidence_task_captured
    ON focus_agent_team_evidence(task_id, captured_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_focus_agent_team_evidence_session_kind
    ON focus_agent_team_evidence(session_id, evidence_kind, captured_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_focus_agent_team_events_task_created
    ON focus_agent_team_events(task_id, created_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_focus_agent_team_events_session_created
    ON focus_agent_team_events(session_id, created_at DESC)
    """,
)


def _run_migration_v19(execute: Callable[..., object]) -> None:
    for statement in _AGENT_TEAM_V2_SCHEMA_STATEMENTS:
        execute(statement)


_MIGRATIONS = (*_BASE_MIGRATIONS, (SCHEMA_VERSION, _run_migration_v19))


def app_postgres_schema_baseline_statements() -> tuple[str, ...]:
    statements = [
        f"SELECT pg_advisory_xact_lock({_SCHEMA_MIGRATION_LOCK_ID})",
        """
        CREATE TABLE IF NOT EXISTS focus_schema_migrations (
            version INT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
    ]
    for version, migration in _MIGRATIONS:
        if version == 10:
            continue
        migration(statements.append)
        statements.append(
            "INSERT INTO focus_schema_migrations (version) "
            f"VALUES ({version}) ON CONFLICT (version) DO NOTHING"
        )
    return tuple(statements)


def app_postgres_schema_baseline_tables() -> tuple[str, ...]:
    tables: list[str] = []
    for statement in app_postgres_schema_baseline_statements():
        match = _CREATED_TABLE_PATTERN.search(statement)
        if match is None:
            continue
        table = match.group("quoted") or match.group("plain")
        if table not in tables:
            tables.append(table)
    return tuple(tables)


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
        _acquire_schema_migration_lock(cur.execute)
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
            cur.execute(
                "SELECT version FROM focus_schema_migrations WHERE version = %s", (version,)
            )
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


def _acquire_schema_migration_lock(execute: Callable[..., object]) -> None:
    execute("SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_MIGRATION_LOCK_ID,))


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


__all__ = [
    "SCHEMA_VERSION",
    "_MIGRATIONS",
    "_run_migration_v10",
    "app_postgres_schema_baseline_statements",
    "app_postgres_schema_baseline_tables",
    "ensure_app_postgres_schema",
    "ensure_app_postgres_schema_on_connection",
    "rebuild_memory_embedding_index",
    "rebuild_memory_embedding_index_on_connection",
]
