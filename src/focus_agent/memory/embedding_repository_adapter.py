from __future__ import annotations

from dataclasses import dataclass

from ..core.repo_call import has_repo_method


@dataclass(frozen=True, slots=True)
class MemoryEmbeddingPayload:
    memory_id: str
    namespace: tuple[str, ...]
    provider_id: str
    model_id: str
    dimensions: int
    content_hash: str
    embedding: list[float]
    metadata: dict[str, object]


def _existing_memory_embedding_content_hash(
    repository: object | None,
    *,
    memory_id: str,
    namespace: tuple[str, ...],
    provider_id: str,
    model_id: str,
) -> str | None:
    if repository is None:
        return None

    if not has_repo_method(repository, "list_embedding_metadata"):
        if has_repo_method(repository, "get_memory_embedding"):
            try:
                return _metadata_content_hash(repository.get_memory_embedding(memory_id=memory_id))
            except TypeError:
                return _metadata_content_hash(repository.get_memory_embedding(memory_id))
        return None

    offset = 0
    batch_size = 500
    while True:
        try:
            rows = repository.list_embedding_metadata(
                namespace=namespace,
                provider_id=provider_id,
                model_id=model_id,
                limit=batch_size,
                offset=offset,
            )
        except TypeError:
            from ..repositories.memory_repository import MemoryEmbeddingListQuery

            rows = repository.list_embedding_metadata(
                MemoryEmbeddingListQuery(
                    namespace=namespace,
                    provider_id=provider_id,
                    model_id=model_id,
                    limit=batch_size,
                    offset=offset,
                )
            )
        if not rows:
            return None
        for row in rows:
            if getattr(row, "memory_id", None) == memory_id or (
                isinstance(row, dict) and row.get("memory_id") == memory_id
            ):
                return _metadata_content_hash(row)
        if len(rows) < batch_size:
            return None
        offset += batch_size


def _upsert_memory_embedding(repository: object, payload: MemoryEmbeddingPayload) -> bool:
    if has_repo_method(repository, "upsert_embedding"):
        repository.upsert_embedding(
            memory_id=payload.memory_id,
            namespace=payload.namespace,
            embedding=payload.embedding,
            provider_id=payload.provider_id,
            model_id=payload.model_id,
            dimensions=payload.dimensions,
            content_hash=payload.content_hash,
            metadata={
                **payload.metadata,
            },
        )
        return True

    if has_repo_method(repository, "upsert_memory_embedding"):
        try:
            repository.upsert_memory_embedding(payload)
        except TypeError:
            repository.upsert_memory_embedding(
                memory_id=payload.memory_id,
                namespace=payload.namespace,
                provider_id=payload.provider_id,
                model_id=payload.model_id,
                dimensions=payload.dimensions,
                content_hash=payload.content_hash,
                embedding=payload.embedding,
                metadata=payload.metadata,
            )
        return True

    return False


def _metadata_content_hash(metadata: object | None) -> str | None:
    if metadata is None:
        return None
    if isinstance(metadata, dict):
        value = metadata.get("content_hash")
    else:
        value = getattr(metadata, "content_hash", None)
    return str(value) if value is not None else None


__all__ = ["MemoryEmbeddingPayload"]
