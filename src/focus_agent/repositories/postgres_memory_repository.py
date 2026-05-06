from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import hashlib
import json
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from focus_agent.memory.models import (
    MemoryAuditEvent,
    MemoryCandidate,
    MemoryRecord,
    MemorySearchHit,
    MemoryStatus,
)

from .memory_repository import (
    MemoryEmbeddingListQuery,
    MemoryEmbeddingMetadata,
    MemoryEmbeddingRecord,
    MemoryEmbeddingSearchHit,
    MemoryListQuery,
    MemoryRepository,
)
from .postgres_schema import (
    ensure_app_postgres_schema_on_connection,
    rebuild_memory_embedding_index_on_connection,
)


class PostgresMemoryRepository(MemoryRepository):
    def __init__(
        self,
        database_uri: str,
        *,
        dimensions: int = 1536,
        vector_index: bool = False,
        memory_embeddings_enabled: bool = False,
        pgvector_extension_mode: str = "auto_create",
    ):
        self.database_uri = database_uri
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
        with psycopg.connect(self.database_uri) as conn:
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

    def _connect(self):
        return psycopg.connect(self.database_uri, row_factory=dict_row)

    def inspect_pgvector_support(
        self,
        *,
        dimensions: int | None = None,
        vector_index: bool = False,
    ) -> dict[str, object]:
        with self._connect() as conn:
            with conn.cursor() as cur:
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
        with psycopg.connect(self.database_uri) as conn:
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
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO focus_memories (
                        memory_id, namespace, kind, scope, visibility, status,
                        user_id, root_thread_id, source_thread_id, source_branch_id,
                        semantic_key, fingerprint, confidence, importance,
                        summary, content, promoted_to_main,
                        created_at, updated_at, deleted_at, data_json
                    ) VALUES (
                        %(memory_id)s, %(namespace)s, %(kind)s, %(scope)s, %(visibility)s, %(status)s,
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
                    _record_params(record, payload=payload),
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
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT data_json
                    FROM focus_memories
                    WHERE {' AND '.join(clauses)}
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    params,
                )
                row = cur.fetchone()
        if row is None:
            return None
        return _record_from_payload(row["data_json"])

    def search(
        self,
        *,
        namespace: tuple[str, ...],
        query: str,
        limit: int,
    ) -> list[MemorySearchHit]:
        normalized_query = " ".join((query or "").split())
        like_query = f"%{normalized_query}%" if normalized_query else "%"
        with self._connect() as conn:
            with conn.cursor() as cur:
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
            record = _record_from_payload(row["data_json"])
            score = float(row.get("text_score") or 0.0)
            hits.append(MemorySearchHit(record=record, score=score, namespace=record.namespace))
        return hits

    def list_records(self, query: MemoryListQuery) -> list[MemoryRecord]:
        clauses = [] if query.status == MemoryStatus.FORGOTTEN.value else ["deleted_at IS NULL"]
        params: dict[str, Any] = {"limit": max(1, int(query.limit)), "offset": max(0, int(query.offset))}
        for field in (
            "kind",
            "scope",
            "visibility",
            "status",
            "user_id",
            "root_thread_id",
            "source_thread_id",
            "source_branch_id",
        ):
            value = getattr(query, field)
            if value is not None:
                clauses.append(f"{field} = %({field})s")
                params[field] = value
        if query.namespace is not None:
            clauses.append("namespace = %(namespace)s")
            params["namespace"] = list(query.namespace)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT data_json
                    FROM focus_memories
                    WHERE {' AND '.join(clauses)}
                    ORDER BY updated_at DESC, memory_id DESC
                    LIMIT %(limit)s OFFSET %(offset)s
                    """,
                    params,
                )
                rows = cur.fetchall()
        return [_record_from_payload(row["data_json"]) for row in rows]

    def get_record(self, memory_id: str) -> MemoryRecord | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT data_json FROM focus_memories WHERE memory_id = %s", (memory_id,))
                row = cur.fetchone()
        if row is None:
            return None
        return _record_from_payload(row["data_json"])

    def upsert_embedding(
        self,
        record: MemoryEmbeddingRecord | None = None,
        *,
        memory_id: str | None = None,
        namespace: tuple[str, ...] | None = None,
        embedding: Sequence[float] | None = None,
        provider_id: str | None = None,
        model_id: str | None = None,
        dimensions: int | None = None,
        status: str = "active",
        content_hash: str | None = None,
        metadata: Mapping[str, object] | None = None,
        **extra: object,
    ) -> str:
        if (
            record is not None
            and not isinstance(record, MemoryEmbeddingRecord)
            and memory_id is None
        ):
            payload = _embedding_payload_dict(record)
            memory_id = str(payload.get("memory_id") or "")
            namespace_value = payload.get("namespace") or ()
            namespace = tuple(str(part) for part in namespace_value)
            embedding_value = payload.get("embedding")
            embedding = embedding_value if isinstance(embedding_value, Sequence) else None
            provider_id = _coalesce_text(payload.get("provider_id"), payload.get("provider"), provider_id)
            model_id = _coalesce_text(payload.get("model_id"), payload.get("model"), model_id)
            dimensions = _coalesce_int(payload.get("dimensions"), dimensions)
            status = str(payload.get("status") or status)
            content_hash = _coalesce_text(payload.get("content_hash"), content_hash)
            metadata = _coerce_metadata(payload.get("metadata"))
            extra = {**{str(key): value for key, value in payload.items()}, **extra}
            created_at = payload.get("created_at")
            updated_at = payload.get("updated_at")
        elif isinstance(record, MemoryEmbeddingRecord):
            memory_id = record.memory_id
            namespace = record.namespace
            embedding = record.embedding
            provider_id = record.provider_id
            model_id = record.model_id
            status = record.status
            content_hash = record.content_hash
            metadata = record.metadata
            dimensions = record.dimensions or len(record.embedding)
            created_at = record.created_at
            updated_at = record.updated_at
        else:
            created_at = None
            updated_at = None
        if provider_id is None:
            provider_id = _coalesce_text(extra.get("provider"), extra.get("provider_id"), "unknown")
        if model_id is None:
            model_id = _coalesce_text(extra.get("model"), extra.get("model_id"), "unknown")
        if memory_id is None or not memory_id or namespace is None:
            raise ValueError("memory_id and namespace are required")
        values = [] if embedding is None else _embedding_values(embedding)
        if not values:
            raise ValueError("embedding must not be empty")
        if dimensions is None:
            dimensions = len(values)
        embedding_id = _memory_embedding_id(
            memory_id=memory_id,
            provider_id=provider_id,
            model_id=model_id,
            content_hash=content_hash or "",
        )
        metadata_payload = {
            **dict(metadata or {}),
            **_embedding_extra_metadata(extra),
        }
        now = datetime.now(timezone.utc)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE focus_memory_embeddings
                    SET
                        status = 'stale',
                        deleted_at = %(updated_at)s,
                        updated_at = %(updated_at)s,
                        metadata_json = metadata_json || %(stale_metadata_json)s
                    WHERE memory_id = %(memory_id)s
                      AND provider_id = %(provider_id)s
                      AND model_id = %(model_id)s
                      AND content_hash <> %(content_hash)s
                      AND status = 'active'
                      AND deleted_at IS NULL
                    """,
                    {
                        "memory_id": memory_id,
                        "provider_id": provider_id,
                        "model_id": model_id,
                        "content_hash": content_hash or "",
                        "updated_at": now,
                        "stale_metadata_json": Jsonb(
                            {
                                "stale_reason": "memory_content_changed",
                                "replaced_by_content_hash": content_hash or "",
                            }
                        ),
                    },
                )
                cur.execute(
                    """
                    INSERT INTO focus_memory_embeddings (
                        embedding_id, memory_id, namespace, provider_id, model_id, dimensions,
                        content_hash, embedding, status, created_at, updated_at, deleted_at, metadata_json
                    ) VALUES (
                        %(embedding_id)s, %(memory_id)s, %(namespace)s, %(provider_id)s, %(model_id)s,
                        %(dimensions)s, %(content_hash)s, %(embedding)s::vector, %(status)s,
                        %(created_at)s, %(updated_at)s, NULL, %(metadata_json)s
                    )
                    ON CONFLICT (embedding_id)
                    DO UPDATE SET
                        memory_id = EXCLUDED.memory_id,
                        namespace = EXCLUDED.namespace,
                        provider_id = EXCLUDED.provider_id,
                        model_id = EXCLUDED.model_id,
                        dimensions = EXCLUDED.dimensions,
                        content_hash = EXCLUDED.content_hash,
                        embedding = EXCLUDED.embedding,
                        status = EXCLUDED.status,
                        deleted_at = NULL,
                        metadata_json = EXCLUDED.metadata_json,
                        updated_at = EXCLUDED.updated_at
                    """,
                    {
                        "embedding_id": embedding_id,
                        "memory_id": memory_id,
                        "namespace": list(namespace),
                        "provider_id": provider_id,
                        "model_id": model_id,
                        "dimensions": len(values),
                        "embedding": _vector_literal(values),
                        "status": status,
                        "content_hash": content_hash or "",
                        "metadata_json": Jsonb(metadata_payload),
                        "created_at": created_at or now,
                        "updated_at": updated_at or now,
                    },
                )
        return memory_id

    def upsert_memory_embedding(self, payload: object | None = None, **kwargs: object) -> str:
        return self.upsert_embedding(payload, **kwargs)

    def upsert_memory_record_embedding(
        self,
        payload: object | None = None,
        **kwargs: object,
    ) -> str:
        return self.upsert_memory_embedding(payload, **kwargs)

    def put_memory_embedding(self, payload: object | None = None, **kwargs: object) -> str:
        return self.upsert_memory_embedding(payload, **kwargs)

    def search_embeddings(
        self,
        *,
        namespace: tuple[str, ...],
        embedding: Sequence[float],
        limit: int,
        provider_id: str | None = None,
        model_id: str | None = None,
        model: str | None = None,
        status: str = "active",
    ) -> list[MemoryEmbeddingSearchHit]:
        values = _embedding_values(embedding)
        if model_id is None:
            model_id = model
        params: dict[str, Any] = {
            "namespace": list(namespace),
            "embedding": _vector_literal(values),
            "dimensions": len(values),
            "status": status,
            "limit": max(1, int(limit)),
        }
        clauses = [
            "e.namespace = %(namespace)s",
            "e.status = %(status)s",
            "e.dimensions = %(dimensions)s",
            "m.status = 'active'",
            "m.deleted_at IS NULL",
            "e.deleted_at IS NULL",
        ]
        if provider_id is not None:
            clauses.append("e.provider_id = %(provider_id)s")
            params["provider_id"] = provider_id
        if model_id is not None:
            clauses.append("e.model_id = %(model_id)s")
            params["model_id"] = model_id
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        m.data_json,
                        e.embedding_id,
                        e.memory_id,
                        e.namespace,
                        e.provider_id,
                        e.model_id,
                        e.dimensions,
                        e.status,
                        e.content_hash,
                        e.metadata_json,
                        e.created_at,
                        e.updated_at,
                        (1.0 - (e.embedding <=> %(embedding)s::vector)) AS score
                    FROM focus_memory_embeddings e
                    JOIN focus_memories m ON m.memory_id = e.memory_id
                    WHERE {' AND '.join(clauses)}
                    ORDER BY score DESC, m.importance DESC, e.updated_at DESC, e.memory_id DESC
                    LIMIT %(limit)s
                    """,
                    params,
                )
                rows = cur.fetchall()
        hits: list[MemoryEmbeddingSearchHit] = []
        for row in rows:
            record = _record_from_payload(row["data_json"])
            score = float(row.get("score") or 0.0)
            hits.append(
                MemoryEmbeddingSearchHit(
                    embedding_id=str(row["embedding_id"]),
                    memory_id=str(row["memory_id"]),
                    record=record,
                    score=score,
                    distance=1.0 - score,
                    namespace=tuple(row["namespace"]),
                    provider_id=str(row["provider_id"]),
                    model_id=str(row["model_id"]),
                    dimensions=int(row["dimensions"]),
                    status=str(row["status"]),
                    content_hash=row["content_hash"],
                    metadata=_decode_json(row["metadata_json"]),
                )
            )
        return hits

    def search_vector(
        self,
        *,
        namespace: tuple[str, ...],
        embedding: Sequence[float],
        provider_id: str,
        model_id: str,
        limit: int,
    ) -> list[MemoryEmbeddingSearchHit]:
        return self.search_embeddings(
            namespace=namespace,
            embedding=embedding,
            provider_id=provider_id,
            model_id=model_id,
            limit=limit,
        )

    def search_memory_embeddings(
        self,
        *,
        namespace: tuple[str, ...],
        embedding: Sequence[float],
        limit: int,
        provider_id: str | None = None,
        model_id: str | None = None,
        model: str | None = None,
        status: str = "active",
    ) -> list[MemoryEmbeddingSearchHit]:
        return self.search_embeddings(
            namespace=namespace,
            embedding=embedding,
            limit=limit,
            provider_id=provider_id,
            model_id=model_id,
            model=model,
            status=status,
        )

    def get_embedding_status(self, memory_id: str) -> str | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT status
                    FROM focus_memory_embeddings
                    WHERE memory_id = %s AND deleted_at IS NULL
                    ORDER BY updated_at DESC, embedding_id DESC
                    LIMIT 1
                    """,
                    (memory_id,),
                )
                row = cur.fetchone()
        return None if row is None else str(row["status"])

    def get_memory_embedding(self, memory_id: str) -> MemoryEmbeddingMetadata | None:
        return self.get_embedding_metadata(memory_id)

    def get_memory_record_embedding(self, memory_id: str) -> MemoryEmbeddingMetadata | None:
        return self.get_embedding_metadata(memory_id)

    def get_embedding(self, memory_id: str) -> MemoryEmbeddingMetadata | None:
        return self.get_embedding_metadata(memory_id)

    def find_memory_embedding(self, memory_id: str) -> MemoryEmbeddingMetadata | None:
        return self.get_embedding_metadata(memory_id)

    def get_embedding_metadata(self, memory_id: str) -> MemoryEmbeddingMetadata | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        embedding_id,
                        memory_id,
                        namespace,
                        provider_id,
                        model_id,
                        dimensions,
                        status,
                        content_hash,
                        metadata_json,
                        created_at,
                        updated_at
                    FROM focus_memory_embeddings
                    WHERE memory_id = %s AND deleted_at IS NULL
                    """,
                    (memory_id,),
                )
                row = cur.fetchone()
        return None if row is None else _embedding_metadata_from_row(row)

    def update_embedding_status(
        self,
        *,
        memory_id: str,
        status: str,
        metadata: Mapping[str, object] | None = None,
    ) -> bool:
        now = datetime.now(timezone.utc)
        with self._connect() as conn:
            with conn.cursor() as cur:
                if metadata is None:
                    cur.execute(
                        """
                        UPDATE focus_memory_embeddings
                        SET status = %(status)s, updated_at = %(updated_at)s
                        WHERE memory_id = %(memory_id)s AND deleted_at IS NULL
                        """,
                        {
                            "memory_id": memory_id,
                            "status": status,
                            "updated_at": now,
                        },
                    )
                else:
                    cur.execute(
                        """
                        UPDATE focus_memory_embeddings
                        SET
                            status = %(status)s,
                            metadata_json = metadata_json || %(metadata_json)s,
                            updated_at = %(updated_at)s
                        WHERE memory_id = %(memory_id)s AND deleted_at IS NULL
                        """,
                        {
                            "memory_id": memory_id,
                            "status": status,
                            "metadata_json": Jsonb(dict(metadata)),
                            "updated_at": now,
                        },
                    )
                rowcount = cur.rowcount
        return rowcount > 0

    def set_memory_embedding_status(
        self,
        *,
        memory_id: str,
        status: str,
        metadata: Mapping[str, object] | None = None,
    ) -> bool:
        return self.update_embedding_status(
            memory_id=memory_id,
            status=status,
            metadata=metadata,
        )

    def list_embedding_metadata(
        self,
        query: MemoryEmbeddingListQuery | None = None,
        *,
        namespace: tuple[str, ...] | None = None,
        provider_id: str | None = None,
        model_id: str | None = None,
        model: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryEmbeddingMetadata]:
        if query is not None:
            namespace = query.namespace
            provider_id = query.provider_id
            model_id = query.model_id
            status = query.status
            limit = query.limit
            offset = query.offset
        if model_id is None:
            model_id = model
        params: dict[str, Any] = {
            "limit": max(1, int(limit)),
            "offset": max(0, int(offset)),
        }
        clauses: list[str] = ["deleted_at IS NULL"]
        if namespace is not None:
            clauses.append("namespace = %(namespace)s")
            params["namespace"] = list(namespace)
        if provider_id is not None:
            clauses.append("provider_id = %(provider_id)s")
            params["provider_id"] = provider_id
        if model_id is not None:
            clauses.append("model_id = %(model_id)s")
            params["model_id"] = model_id
        if status is not None:
            clauses.append("status = %(status)s")
            params["status"] = status
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        embedding_id,
                        memory_id,
                        namespace,
                        provider_id,
                        model_id,
                        dimensions,
                        status,
                        content_hash,
                        metadata_json,
                        created_at,
                        updated_at
                    FROM focus_memory_embeddings
                    {where}
                    ORDER BY updated_at DESC, memory_id DESC
                    LIMIT %(limit)s OFFSET %(offset)s
                    """,
                    params,
                )
                rows = cur.fetchall()
        return [_embedding_metadata_from_row(row) for row in rows]

    def list_memory_embedding_metadata(
        self,
        query: MemoryEmbeddingListQuery | None = None,
        *,
        namespace: tuple[str, ...] | None = None,
        provider_id: str | None = None,
        model_id: str | None = None,
        model: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryEmbeddingMetadata]:
        return self.list_embedding_metadata(
            query,
            namespace=namespace,
            provider_id=provider_id,
            model_id=model_id,
            model=model,
            status=status,
            limit=limit,
            offset=offset,
        )

    def delete_embedding(self, memory_id: str) -> bool:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM focus_memory_embeddings WHERE memory_id = %s", (memory_id,))
                rowcount = cur.rowcount
        return rowcount > 0

    def delete_memory_embedding(self, memory_id: str) -> bool:
        return self.delete_embedding(memory_id)

    def delete_memory_embeddings(self, memory_id: str) -> int:
        return 1 if self.delete_embedding(memory_id) else 0

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
        now = datetime.now(timezone.utc)
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
        with self._connect() as conn:
            with conn.cursor() as cur:
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
        with self._connect() as conn:
            with conn.cursor() as cur:
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
        params: dict[str, Any] = {"limit": max(1, int(limit))}
        clauses: list[str] = []
        for field, value in (
            ("memory_id", memory_id),
            ("user_id", user_id),
            ("root_thread_id", root_thread_id),
            ("source_thread_id", source_thread_id),
            ("source_branch_id", source_branch_id),
        ):
            if value is not None:
                clauses.append(f"{field} = %({field})s")
                params[field] = value
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            with conn.cursor() as cur:
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
        return [MemoryAuditEvent.model_validate(_decode_json(row["data_json"])) for row in rows]

    def upsert_candidate(self, candidate: MemoryCandidate) -> str:
        payload = candidate.model_dump(mode="json")
        with self._connect() as conn:
            with conn.cursor() as cur:
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
        clauses: list[str] = []
        params: dict[str, Any] = {"limit": max(1, int(limit))}
        if status:
            clauses.append("status = %(status)s")
            params["status"] = status
        if root_thread_id:
            clauses.append("root_thread_id = %(root_thread_id)s")
            params["root_thread_id"] = root_thread_id
        if user_id:
            clauses.append("user_id = %(user_id)s")
            params["user_id"] = user_id
        if branch_id:
            clauses.append("branch_id = %(branch_id)s")
            params["branch_id"] = branch_id
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            with conn.cursor() as cur:
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
        return [MemoryCandidate.model_validate(_decode_json(row["data_json"])) for row in rows]

    def update_candidate_status(
        self,
        *,
        candidate_id: str,
        status: str,
        reason: str | None = None,
    ) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
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
        candidate = MemoryCandidate.model_validate(_decode_json(row["data_json"]))
        now = datetime.now(timezone.utc)
        updated = candidate.model_copy(update={"status": status, "reason": reason, "updated_at": now})
        self.upsert_candidate(updated)


def _record_params(record: MemoryRecord, *, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "memory_id": record.memory_id,
        "namespace": list(record.namespace),
        "kind": record.kind.value,
        "scope": record.scope.value,
        "visibility": record.visibility.value,
        "status": record.status.value,
        "user_id": record.user_id,
        "root_thread_id": record.root_thread_id,
        "source_thread_id": record.source_thread_id,
        "source_branch_id": record.source_branch_id,
        "semantic_key": record.semantic_key,
        "fingerprint": record.fingerprint,
        "confidence": record.confidence,
        "importance": record.importance,
        "summary": record.summary,
        "content": record.content,
        "promoted_to_main": record.promoted_to_main,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "deleted_at": record.deleted_at,
        "data_json": Jsonb(payload),
    }


def _embedding_values(embedding: Sequence[float]) -> list[float]:
    values = [float(value) for value in embedding]
    if not values:
        raise ValueError("embedding must not be empty")
    return values


def _vector_literal(values: Sequence[float]) -> str:
    return "[" + ",".join(f"{float(value):.12g}" for value in values) + "]"


def _memory_embedding_id(
    *,
    memory_id: str,
    provider_id: str,
    model_id: str,
    content_hash: str,
) -> str:
    seed = json.dumps(
        {
            "memory_id": memory_id,
            "provider_id": provider_id,
            "model_id": model_id,
            "content_hash": content_hash,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return f"mem-emb:{hashlib.sha256(seed.encode('utf-8')).hexdigest()}"


def _embedding_payload_dict(payload: object) -> dict[str, object]:
    if isinstance(payload, dict):
        return dict(payload)
    model_dump = getattr(payload, "model_dump", None)
    if callable(model_dump):
        return dict(model_dump(mode="python"))
    if hasattr(payload, "__dataclass_fields__"):
        return {
            field_name: getattr(payload, field_name)
            for field_name in payload.__dataclass_fields__
        }
    return {
        name: getattr(payload, name)
        for name in dir(payload)
        if not name.startswith("_") and not callable(getattr(payload, name))
    }


def _coalesce_text(*values: object) -> str | None:
    for value in values:
        if value is not None:
            text = str(value)
            if text:
                return text
    return None


def _coalesce_int(*values: object) -> int | None:
    for value in values:
        if value is not None:
            return int(value)
    return None


def _coerce_metadata(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return {}


def _embedding_extra_metadata(extra: Mapping[str, object]) -> dict[str, object]:
    metadata: dict[str, object] = {}
    for key in ("kind", "scope", "embedding_text", "text"):
        value = extra.get(key)
        if value is not None:
            metadata[key] = value
    return metadata


def _embedding_metadata_from_row(row: dict[str, Any]) -> MemoryEmbeddingMetadata:
    return MemoryEmbeddingMetadata(
        embedding_id=str(row["embedding_id"]) if row.get("embedding_id") is not None else None,
        memory_id=str(row["memory_id"]),
        namespace=tuple(row["namespace"]),
        provider_id=str(row["provider_id"]),
        model_id=str(row["model_id"]),
        dimensions=int(row["dimensions"]),
        status=str(row["status"]),
        content_hash=row["content_hash"],
        metadata=_decode_json(row["metadata_json"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _record_from_payload(payload: object) -> MemoryRecord:
    data = _decode_json(payload)
    return MemoryRecord.model_validate(data)


def _decode_json(value: object) -> dict[str, Any]:
    if isinstance(value, str):
        return json.loads(value)
    if isinstance(value, dict):
        return value
    return dict(value)  # type: ignore[arg-type]


__all__ = ["PostgresMemoryRepository"]
