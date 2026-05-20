from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from focus_agent.memory.models import (
    MemoryAuditEvent,
    MemoryCandidate,
    MemoryRecord,
    MemorySearchHit,
    MemoryStatus,
)
from focus_agent.storage.postgres import PostgresConnectionProvider

from ._postgres_base import PostgresMixin
from .memory_repository import (
    MemoryListQuery,
    MemoryRepository,
)
from .postgres_memory_embeddings import PostgresMemoryEmbeddingMixin
from .postgres_memory_mappers import (
    decode_json,
    record_from_payload,
    record_params,
)
from .postgres_memory_queries import (
    audit_event_filters,
    candidate_filters,
    memory_list_filters,
    where_clause,
)
from .postgres_schema import (
    ensure_app_postgres_schema_on_connection,
    rebuild_memory_embedding_index_on_connection,
)

_PSYCOPG_MODULE = psycopg  # Preserve the legacy monkeypatch path used by unit tests.


class PostgresMemoryRepository(PostgresMemoryEmbeddingMixin, PostgresMixin, MemoryRepository):
    def __init__(
        self,
        database_uri: str,
        *,
        connection_provider: PostgresConnectionProvider | None = None,
        dimensions: int = 1536,
        vector_index: bool = False,
        memory_embeddings_enabled: bool = False,
        pgvector_extension_mode: str = "auto_create",
    ):
        self.database_uri = database_uri
        self.connection_provider = connection_provider
        self.dimensions = dimensions
        self.vector_index = vector_index
        self.memory_embeddings_enabled = memory_embeddings_enabled
        self.pgvector_extension_mode = pgvector_extension_mode

    def setup(
        self,
        *,
        dimensions: int | None = None,
        vector_index: bool | None = None,
        memory_embeddings_enabled: bool | None = None,
        pgvector_extension_mode: str | None = None,
    ) -> None:
        with self._connection() as conn:
            ensure_app_postgres_schema_on_connection(
                conn,
                dimensions=self.dimensions if dimensions is None else dimensions,
                vector_index=self.vector_index if vector_index is None else vector_index,
                memory_embeddings_enabled=(
                    self.memory_embeddings_enabled
                    if memory_embeddings_enabled is None
                    else memory_embeddings_enabled
                ),
                pgvector_extension_mode=(
                    self.pgvector_extension_mode
                    if pgvector_extension_mode is None
                    else pgvector_extension_mode
                ),
            )

    def inspect_pgvector_support(
        self,
        *,
        dimensions: int | None = None,
        vector_index: bool = False,
    ) -> dict[str, object]:
        with self._cursor(dict_row=True) as cur:
            cur.execute(
                """
                    SELECT
                        EXISTS (
                            SELECT 1 FROM pg_extension WHERE extname = 'vector'
                        ) AS extension_installed,
                        (
                            SELECT extversion FROM pg_extension WHERE extname = 'vector'
                        ) AS extension_version,
                        to_regclass('focus_memory_embeddings') IS NOT NULL AS embeddings_table_exists,
                        (
                            SELECT format_type(a.atttypid, a.atttypmod)
                            FROM pg_attribute a
                            WHERE a.attrelid = to_regclass('focus_memory_embeddings')
                              AND a.attname = 'embedding'
                              AND NOT a.attisdropped
                        ) AS embedding_column_type,
                        EXISTS (
                            SELECT 1
                            FROM pg_indexes
                            WHERE indexname = 'idx_focus_memory_embeddings_vector'
                        ) AS vector_index_exists
                    """
            )
            row = cur.fetchone() or {}
        table_exists = bool(row.get("embeddings_table_exists"))
        column_type = row.get("embedding_column_type")
        configured_dimensions = self.dimensions if dimensions is None else dimensions
        return {
            "extension_installed": bool(row.get("extension_installed")),
            "extension_version": row.get("extension_version"),
            "embeddings_table_exists": table_exists,
            "embedding_column_type": column_type,
            "configured_dimensions": configured_dimensions,
            "dimensions_match": (
                not table_exists
                or str(column_type) == f"vector({max(1, int(configured_dimensions))})"
            ),
            "vector_index_expected": bool(vector_index),
            "vector_index_exists": bool(row.get("vector_index_exists")),
        }

    def rebuild_embedding_index(
        self,
        *,
        dimensions: int | None = None,
        vector_index: bool | None = None,
        pgvector_extension_mode: str | None = None,
    ) -> dict[str, object]:
        resolved_dimensions = self.dimensions if dimensions is None else max(1, int(dimensions))
        resolved_vector_index = self.vector_index if vector_index is None else bool(vector_index)
        resolved_extension_mode = (
            self.pgvector_extension_mode
            if pgvector_extension_mode is None
            else pgvector_extension_mode
        )
        with self._connection() as conn:
            rebuild_memory_embedding_index_on_connection(
                conn,
                dimensions=resolved_dimensions,
                vector_index=resolved_vector_index,
                pgvector_extension_mode=resolved_extension_mode,
            )
        self.dimensions = resolved_dimensions
        self.vector_index = resolved_vector_index
        self.pgvector_extension_mode = resolved_extension_mode
        self.memory_embeddings_enabled = True
        return self.inspect_pgvector_support(
            dimensions=resolved_dimensions,
            vector_index=resolved_vector_index,
        )

    def upsert_record(self, record: MemoryRecord) -> str:
        payload = record.model_dump(mode="json")
        with self._cursor(dict_row=True) as cur:
            cur.execute(
                """
                    INSERT INTO focus_memories (
                        memory_id, namespace, kind, scope, visibility, status,
                        embedding_status,
                        user_id, root_thread_id, source_thread_id, source_branch_id,
                        semantic_key, fingerprint, confidence, importance,
                        summary, content, promoted_to_main,
                        created_at, updated_at, deleted_at, data_json
                    ) VALUES (
                        %(memory_id)s, %(namespace)s, %(kind)s, %(scope)s, %(visibility)s, %(status)s,
                        %(embedding_status)s,
                        %(user_id)s, %(root_thread_id)s, %(source_thread_id)s, %(source_branch_id)s,
                        %(semantic_key)s, %(fingerprint)s, %(confidence)s, %(importance)s,
                        %(summary)s, %(content)s, %(promoted_to_main)s,
                        %(created_at)s, %(updated_at)s, %(deleted_at)s, %(data_json)s
                    )
                    ON CONFLICT (memory_id) DO UPDATE SET
                        namespace = EXCLUDED.namespace,
                        kind = EXCLUDED.kind,
                        scope = EXCLUDED.scope,
                        visibility = EXCLUDED.visibility,
                        status = EXCLUDED.status,
                        embedding_status = EXCLUDED.embedding_status,
                        user_id = EXCLUDED.user_id,
                        root_thread_id = EXCLUDED.root_thread_id,
                        source_thread_id = EXCLUDED.source_thread_id,
                        source_branch_id = EXCLUDED.source_branch_id,
                        semantic_key = EXCLUDED.semantic_key,
                        fingerprint = EXCLUDED.fingerprint,
                        confidence = EXCLUDED.confidence,
                        importance = EXCLUDED.importance,
                        summary = EXCLUDED.summary,
                        content = EXCLUDED.content,
                        promoted_to_main = EXCLUDED.promoted_to_main,
                        updated_at = EXCLUDED.updated_at,
                        deleted_at = EXCLUDED.deleted_at,
                        data_json = EXCLUDED.data_json
                    """,
                record_params(record, payload=payload),
            )
        return record.memory_id

    def find_existing(
        self,
        *,
        namespace: tuple[str, ...],
        fingerprint: str,
        semantic_key: str,
        kind: str | None = None,
        scope: str | None = None,
    ) -> MemoryRecord | None:
        clauses = [
            "namespace = %(namespace)s",
            "status != 'forgotten'",
            "deleted_at IS NULL",
            "(fingerprint = %(fingerprint)s OR semantic_key = %(semantic_key)s)",
        ]
        params: dict[str, Any] = {
            "namespace": list(namespace),
            "fingerprint": fingerprint,
            "semantic_key": semantic_key,
        }
        if kind:
            clauses.append("kind = %(kind)s")
            params["kind"] = kind
        if scope:
            clauses.append("scope = %(scope)s")
            params["scope"] = scope
        with self._cursor(dict_row=True) as cur:
            cur.execute(
                f"""
                    SELECT data_json
                    FROM focus_memories
                    WHERE {" AND ".join(clauses)}
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                params,
            )
            row = cur.fetchone()
        if row is None:
            return None
        return record_from_payload(row["data_json"])

    def search(
        self,
        *,
        namespace: tuple[str, ...],
        query: str,
        limit: int,
    ) -> list[MemorySearchHit]:
        normalized_query = " ".join((query or "").split())
        like_query = f"%{normalized_query}%" if normalized_query else "%"
        with self._cursor(dict_row=True) as cur:
            cur.execute(
                """
                    SELECT data_json,
                           CASE
                             WHEN %(query)s = '' THEN 0.0
                             ELSE ts_rank_cd(
                               to_tsvector('simple', coalesce(summary, '') || ' ' || coalesce(content, '')),
                               plainto_tsquery('simple', %(query)s)
                             )
                           END AS text_score
                    FROM focus_memories
                    WHERE namespace = %(namespace)s
                      AND status = 'active'
                      AND deleted_at IS NULL
                      AND (
                        %(query)s = ''
                        OR to_tsvector('simple', coalesce(summary, '') || ' ' || coalesce(content, ''))
                           @@ plainto_tsquery('simple', %(query)s)
                        OR summary ILIKE %(like_query)s
                        OR content ILIKE %(like_query)s
                      )
                    ORDER BY text_score DESC, importance DESC, updated_at DESC
                    LIMIT %(limit)s
                    """,
                {
                    "namespace": list(namespace),
                    "query": normalized_query,
                    "like_query": like_query,
                    "limit": max(1, int(limit)),
                },
            )
            rows = cur.fetchall()
        hits: list[MemorySearchHit] = []
        for row in rows:
            record = record_from_payload(row["data_json"])
            score = float(row.get("text_score") or 0.0)
            hits.append(MemorySearchHit(record=record, score=score, namespace=record.namespace))
        return hits

    def list_records(self, query: MemoryListQuery) -> list[MemoryRecord]:
        clauses, params = memory_list_filters(query)
        with self._cursor(dict_row=True) as cur:
            cur.execute(
                f"""
                    SELECT data_json
                    FROM focus_memories
                    WHERE {" AND ".join(clauses)}
                    ORDER BY updated_at DESC, memory_id DESC
                    LIMIT %(limit)s OFFSET %(offset)s
                    """,
                params,
            )
            rows = cur.fetchall()
        return [record_from_payload(row["data_json"]) for row in rows]

    def get_record(self, memory_id: str) -> MemoryRecord | None:
        with self._cursor(dict_row=True) as cur:
            cur.execute("SELECT data_json FROM focus_memories WHERE memory_id = %s", (memory_id,))
            row = cur.fetchone()
        if row is None:
            return None
        return record_from_payload(row["data_json"])


    def forget_record(
        self,
        *,
        memory_id: str,
        namespace: tuple[str, ...] | None = None,
        actor: str | None = None,
        reason: str | None = None,
    ) -> str | None:
        existing = self.get_record(memory_id)
        if existing is None:
            return None
        if namespace is not None and existing.namespace != namespace:
            return None
        now = datetime.now(UTC)
        updated = existing.model_copy(
            update={
                "status": MemoryStatus.FORGOTTEN,
                "content": "",
                "summary": "[forgotten]",
                "deleted_at": now,
                "updated_at": now,
            }
        )
        self.upsert_record(updated)
        tombstone_id = str(uuid4())
        with self._cursor(dict_row=True) as cur:
            cur.execute(
                """
                    INSERT INTO focus_memory_tombstones (
                        tombstone_id, memory_id, namespace, semantic_key, fingerprint,
                        actor, reason, created_at, data_json
                    ) VALUES (
                        %(tombstone_id)s, %(memory_id)s, %(namespace)s, %(semantic_key)s, %(fingerprint)s,
                        %(actor)s, %(reason)s, %(created_at)s, %(data_json)s
                    )
                    ON CONFLICT (memory_id) DO UPDATE SET
                        namespace = EXCLUDED.namespace,
                        semantic_key = EXCLUDED.semantic_key,
                        fingerprint = EXCLUDED.fingerprint,
                        actor = EXCLUDED.actor,
                        reason = EXCLUDED.reason,
                        created_at = EXCLUDED.created_at,
                        data_json = EXCLUDED.data_json
                    RETURNING tombstone_id
                    """,
                {
                    "tombstone_id": tombstone_id,
                    "memory_id": memory_id,
                    "namespace": list(existing.namespace),
                    "semantic_key": existing.semantic_key,
                    "fingerprint": existing.fingerprint,
                    "actor": actor,
                    "reason": reason,
                    "created_at": now,
                    "data_json": Jsonb(
                        {
                            "memory_id": memory_id,
                            "namespace": list(existing.namespace),
                            "semantic_key": existing.semantic_key,
                            "fingerprint": existing.fingerprint,
                            "actor": actor,
                            "reason": reason,
                            "created_at": now.isoformat(),
                        }
                    ),
                },
            )
            row = cur.fetchone()
        self.delete_embedding(memory_id)
        return str(row["tombstone_id"]) if row else tombstone_id

    def append_audit_event(self, event: MemoryAuditEvent) -> str:
        payload = event.model_dump(mode="json")
        with self._cursor(dict_row=True) as cur:
            cur.execute(
                """
                    INSERT INTO focus_memory_audit_events (
                        event_id, action, decision, memory_id, candidate_id, actor,
                        reason, namespace, user_id, root_thread_id, source_thread_id,
                        source_branch_id, request_id, created_at, data_json
                    ) VALUES (
                        %(event_id)s, %(action)s, %(decision)s, %(memory_id)s, %(candidate_id)s, %(actor)s,
                        %(reason)s, %(namespace)s, %(user_id)s, %(root_thread_id)s, %(source_thread_id)s,
                        %(source_branch_id)s, %(request_id)s, %(created_at)s, %(data_json)s
                    )
                    ON CONFLICT (event_id) DO NOTHING
                    """,
                {
                    **payload,
                    "decision": str(payload.get("decision") or ""),
                    "namespace": list(event.namespace),
                    "data_json": Jsonb(payload),
                },
            )
        return event.event_id

    def list_audit_events(
        self,
        *,
        memory_id: str | None = None,
        user_id: str | None = None,
        root_thread_id: str | None = None,
        source_thread_id: str | None = None,
        source_branch_id: str | None = None,
        limit: int = 50,
    ) -> list[MemoryAuditEvent]:
        clauses, params = audit_event_filters(
            memory_id=memory_id,
            user_id=user_id,
            root_thread_id=root_thread_id,
            source_thread_id=source_thread_id,
            source_branch_id=source_branch_id,
            limit=limit,
        )
        where = where_clause(clauses)
        with self._cursor(dict_row=True) as cur:
            cur.execute(
                f"""
                    SELECT data_json
                    FROM focus_memory_audit_events
                    {where}
                    ORDER BY created_at DESC, event_id DESC
                    LIMIT %(limit)s
                    """,
                params,
            )
            rows = cur.fetchall()
        return [MemoryAuditEvent.model_validate(decode_json(row["data_json"])) for row in rows]

    def upsert_candidate(self, candidate: MemoryCandidate) -> str:
        payload = candidate.model_dump(mode="json")
        with self._cursor(dict_row=True) as cur:
            cur.execute(
                """
                    INSERT INTO focus_memory_candidates (
                        candidate_id, status, agent_id, task_id, branch_id,
                        root_thread_id, user_id, evidence_refs, created_at, updated_at, data_json
                    ) VALUES (
                        %(candidate_id)s, %(status)s, %(agent_id)s, %(task_id)s, %(branch_id)s,
                        %(root_thread_id)s, %(user_id)s, %(evidence_refs)s, %(created_at)s,
                        %(updated_at)s, %(data_json)s
                    )
                    ON CONFLICT (candidate_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        agent_id = EXCLUDED.agent_id,
                        task_id = EXCLUDED.task_id,
                        branch_id = EXCLUDED.branch_id,
                        root_thread_id = EXCLUDED.root_thread_id,
                        user_id = EXCLUDED.user_id,
                        evidence_refs = EXCLUDED.evidence_refs,
                        updated_at = EXCLUDED.updated_at,
                        data_json = EXCLUDED.data_json
                    """,
                {
                    **payload,
                    "evidence_refs": list(candidate.evidence_refs),
                    "data_json": Jsonb(payload),
                },
            )
        return candidate.candidate_id

    def list_candidates(
        self,
        *,
        status: str | None = None,
        root_thread_id: str | None = None,
        user_id: str | None = None,
        branch_id: str | None = None,
        limit: int = 50,
    ) -> list[MemoryCandidate]:
        clauses, params = candidate_filters(
            status=status,
            root_thread_id=root_thread_id,
            user_id=user_id,
            branch_id=branch_id,
            limit=limit,
        )
        where = where_clause(clauses)
        with self._cursor(dict_row=True) as cur:
            cur.execute(
                f"""
                    SELECT data_json
                    FROM focus_memory_candidates
                    {where}
                    ORDER BY updated_at DESC, candidate_id DESC
                    LIMIT %(limit)s
                    """,
                params,
            )
            rows = cur.fetchall()
        return [MemoryCandidate.model_validate(decode_json(row["data_json"])) for row in rows]

    def update_candidate_status(
        self,
        *,
        candidate_id: str,
        status: str,
        reason: str | None = None,
    ) -> None:
        with self._cursor(dict_row=True) as cur:
            cur.execute(
                """
                    SELECT data_json
                    FROM focus_memory_candidates
                    WHERE candidate_id = %s
                    """,
                (candidate_id,),
            )
            row = cur.fetchone()
        if row is None:
            return
        candidate = MemoryCandidate.model_validate(decode_json(row["data_json"]))
        now = datetime.now(UTC)
        updated = candidate.model_copy(
            update={"status": status, "reason": reason, "updated_at": now}
        )
        self.upsert_candidate(updated)


__all__ = ["PostgresMemoryRepository"]
