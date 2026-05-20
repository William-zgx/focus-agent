from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from psycopg.types.json import Jsonb

from .memory_repository import (
    MemoryEmbeddingListQuery,
    MemoryEmbeddingMetadata,
    MemoryEmbeddingRecord,
    MemoryEmbeddingSearchHit,
)
from .postgres_memory_mappers import (
    coalesce_int,
    coalesce_text,
    coerce_metadata,
    decode_json,
    embedding_extra_metadata,
    embedding_metadata_from_row,
    embedding_payload_dict,
    embedding_values,
    memory_embedding_id,
    record_from_payload,
    vector_literal,
)
from .postgres_memory_queries import embedding_list_filters, where_clause


class PostgresMemoryEmbeddingMixin:
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
            payload = embedding_payload_dict(record)
            memory_id = str(payload.get("memory_id") or "")
            namespace_value = payload.get("namespace") or ()
            namespace = tuple(str(part) for part in namespace_value)
            embedding_value = payload.get("embedding")
            embedding = embedding_value if isinstance(embedding_value, Sequence) else None
            provider_id = coalesce_text(
                payload.get("provider_id"), payload.get("provider"), provider_id
            )
            model_id = coalesce_text(payload.get("model_id"), payload.get("model"), model_id)
            dimensions = coalesce_int(payload.get("dimensions"), dimensions)
            status = str(payload.get("status") or status)
            content_hash = coalesce_text(payload.get("content_hash"), content_hash)
            metadata = coerce_metadata(payload.get("metadata"))
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
            provider_id = coalesce_text(extra.get("provider"), extra.get("provider_id"), "unknown")
        if model_id is None:
            model_id = coalesce_text(extra.get("model"), extra.get("model_id"), "unknown")
        if memory_id is None or not memory_id or namespace is None:
            raise ValueError("memory_id and namespace are required")
        values = [] if embedding is None else embedding_values(embedding)
        if not values:
            raise ValueError("embedding must not be empty")
        if dimensions is None:
            dimensions = len(values)
        embedding_id = memory_embedding_id(
            memory_id=memory_id,
            provider_id=provider_id,
            model_id=model_id,
            content_hash=content_hash or "",
        )
        metadata_payload = {
            **dict(metadata or {}),
            **embedding_extra_metadata(extra),
        }
        now = datetime.now(UTC)
        with self._cursor(dict_row=True) as cur:
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
                    "embedding": vector_literal(values),
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
        values = embedding_values(embedding)
        if model_id is None:
            model_id = model
        params: dict[str, Any] = {
            "namespace": list(namespace),
            "embedding": vector_literal(values),
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
        with self._cursor(dict_row=True) as cur:
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
                    WHERE {" AND ".join(clauses)}
                    ORDER BY score DESC, m.importance DESC, e.updated_at DESC, e.memory_id DESC
                    LIMIT %(limit)s
                    """,
                params,
            )
            rows = cur.fetchall()
        hits: list[MemoryEmbeddingSearchHit] = []
        for row in rows:
            record = record_from_payload(row["data_json"])
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
                    metadata=decode_json(row["metadata_json"]),
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
        with self._cursor(dict_row=True) as cur:
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
        with self._cursor(dict_row=True) as cur:
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
        return None if row is None else embedding_metadata_from_row(row)

    def update_embedding_status(
        self,
        *,
        memory_id: str,
        status: str,
        metadata: Mapping[str, object] | None = None,
    ) -> bool:
        now = datetime.now(UTC)
        with self._cursor(dict_row=True) as cur:
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
        clauses, params = embedding_list_filters(
            query,
            namespace=namespace,
            provider_id=provider_id,
            model_id=model_id,
            model=model,
            status=status,
            limit=limit,
            offset=offset,
        )
        where = where_clause(clauses)
        with self._cursor(dict_row=True) as cur:
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
        return [embedding_metadata_from_row(row) for row in rows]

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
        with self._cursor(dict_row=True) as cur:
            cur.execute("DELETE FROM focus_memory_embeddings WHERE memory_id = %s", (memory_id,))
            rowcount = cur.rowcount
        return rowcount > 0

    def delete_memory_embedding(self, memory_id: str) -> bool:
        return self.delete_embedding(memory_id)

    def delete_memory_embeddings(self, memory_id: str) -> int:
        return 1 if self.delete_embedding(memory_id) else 0


__all__ = ["PostgresMemoryEmbeddingMixin"]
