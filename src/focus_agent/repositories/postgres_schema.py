from __future__ import annotations

from collections.abc import Callable

import psycopg

from .postgres_schema_migrations import (
    _MIGRATIONS,
    _run_migration_v10,
)

SCHEMA_VERSION = 18
_SCHEMA_MIGRATION_LOCK_ID = 7612044473148256129


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
    "ensure_app_postgres_schema",
    "ensure_app_postgres_schema_on_connection",
    "rebuild_memory_embedding_index",
    "rebuild_memory_embedding_index_on_connection",
]
