from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from focus_agent.memory.models import (
    MemoryAuditEvent,
    MemoryCandidate,
    MemoryRecord,
    MemorySearchHit,
)


@dataclass(frozen=True, slots=True)
class MemoryListQuery:
    namespace: tuple[str, ...] | None = None
    kind: str | None = None
    scope: str | None = None
    visibility: str | None = None
    status: str | None = None
    user_id: str | None = None
    root_thread_id: str | None = None
    source_thread_id: str | None = None
    source_branch_id: str | None = None
    limit: int = 50
    offset: int = 0


@dataclass(frozen=True, slots=True)
class MemoryEmbeddingRecord:
    memory_id: str
    namespace: tuple[str, ...]
    embedding: tuple[float, ...]
    embedding_id: str | None = None
    provider_id: str = "unknown"
    model_id: str = "unknown"
    dimensions: int | None = None
    status: str = "active"
    content_hash: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class MemoryEmbeddingMetadata:
    embedding_id: str | None
    memory_id: str
    namespace: tuple[str, ...]
    provider_id: str
    model_id: str
    dimensions: int
    status: str
    content_hash: str | None
    metadata: dict[str, object]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class MemoryEmbeddingListQuery:
    namespace: tuple[str, ...] | None = None
    provider_id: str | None = None
    model_id: str | None = None
    status: str | None = None
    limit: int = 50
    offset: int = 0


@dataclass(frozen=True, slots=True)
class MemoryEmbeddingSearchHit:
    embedding_id: str | None
    memory_id: str
    record: MemoryRecord
    score: float
    distance: float
    namespace: tuple[str, ...]
    provider_id: str
    model_id: str
    dimensions: int
    status: str
    content_hash: str | None
    metadata: dict[str, object]


class MemoryRepository(Protocol):
    def setup(
        self,
        *,
        dimensions: int = 1536,
        vector_index: bool = False,
        memory_embeddings_enabled: bool = False,
        pgvector_extension_mode: str = "auto_create",
    ) -> None: ...

    def upsert_record(self, record: MemoryRecord) -> str: ...

    def find_existing(
        self,
        *,
        namespace: tuple[str, ...],
        fingerprint: str,
        semantic_key: str,
        kind: str | None = None,
        scope: str | None = None,
    ) -> MemoryRecord | None: ...

    def search(
        self,
        *,
        namespace: tuple[str, ...],
        query: str,
        limit: int,
    ) -> list[MemorySearchHit]: ...

    def list_records(self, query: MemoryListQuery) -> list[MemoryRecord]: ...

    def get_record(self, memory_id: str) -> MemoryRecord | None: ...

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
    ) -> str: ...

    def upsert_memory_embedding(self, payload: object | None = None, **kwargs: object) -> str: ...

    def get_memory_embedding(self, memory_id: str) -> MemoryEmbeddingMetadata | None: ...

    def search_embeddings(
        self,
        *,
        namespace: tuple[str, ...],
        embedding: Sequence[float],
        limit: int,
        provider_id: str | None = None,
        model_id: str | None = None,
        status: str = "active",
    ) -> list[MemoryEmbeddingSearchHit]: ...

    def search_memory_embeddings(
        self,
        *,
        namespace: tuple[str, ...],
        embedding: Sequence[float],
        limit: int,
        provider_id: str | None = None,
        model_id: str | None = None,
        status: str = "active",
    ) -> list[MemoryEmbeddingSearchHit]: ...

    def get_embedding_status(self, memory_id: str) -> str | None: ...

    def update_embedding_status(
        self,
        *,
        memory_id: str,
        status: str,
        metadata: Mapping[str, object] | None = None,
    ) -> bool: ...

    def set_memory_embedding_status(
        self,
        *,
        memory_id: str,
        status: str,
        metadata: Mapping[str, object] | None = None,
    ) -> bool: ...

    def list_embedding_metadata(
        self,
        query: MemoryEmbeddingListQuery | None = None,
        *,
        namespace: tuple[str, ...] | None = None,
        provider_id: str | None = None,
        model_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryEmbeddingMetadata]: ...

    def list_memory_embedding_metadata(
        self,
        query: MemoryEmbeddingListQuery | None = None,
        *,
        namespace: tuple[str, ...] | None = None,
        provider_id: str | None = None,
        model_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryEmbeddingMetadata]: ...

    def delete_embedding(self, memory_id: str) -> bool: ...

    def delete_memory_embedding(self, memory_id: str) -> bool: ...

    def forget_record(
        self,
        *,
        memory_id: str,
        namespace: tuple[str, ...] | None = None,
        actor: str | None = None,
        reason: str | None = None,
    ) -> str | None: ...

    def append_audit_event(self, event: MemoryAuditEvent) -> str: ...

    def list_audit_events(
        self,
        *,
        memory_id: str | None = None,
        user_id: str | None = None,
        root_thread_id: str | None = None,
        source_thread_id: str | None = None,
        source_branch_id: str | None = None,
        limit: int = 50,
    ) -> list[MemoryAuditEvent]: ...

    def upsert_candidate(self, candidate: MemoryCandidate) -> str: ...

    def list_candidates(
        self,
        *,
        status: str | None = None,
        root_thread_id: str | None = None,
        user_id: str | None = None,
        branch_id: str | None = None,
        limit: int = 50,
    ) -> list[MemoryCandidate]: ...

    def update_candidate_status(
        self,
        *,
        candidate_id: str,
        status: str,
        reason: str | None = None,
    ) -> None: ...


__all__ = [
    "MemoryEmbeddingListQuery",
    "MemoryEmbeddingMetadata",
    "MemoryEmbeddingRecord",
    "MemoryEmbeddingSearchHit",
    "MemoryListQuery",
    "MemoryRepository",
]
