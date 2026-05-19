from __future__ import annotations

from typing import Any

import httpx

from focus_agent.memory.embedding import (
    MemoryEmbeddingService,
    OpenAICompatibleEmbeddingProvider,
)
from focus_agent.memory.models import (
    MemoryAuditEvent,
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemoryVisibility,
    MemoryWriteRequest,
)
from focus_agent.memory.service import MemoryService
from focus_agent.storage.namespaces import user_profile_namespace


class _FakeMemoryRepository:
    def __init__(self) -> None:
        self.records: dict[str, MemoryRecord] = {}
        self.audit_events: list[MemoryAuditEvent] = []

    def upsert_record(self, record: MemoryRecord) -> str:
        self.records[record.memory_id] = record
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
        del namespace, fingerprint, semantic_key, kind, scope
        return None

    def append_audit_event(self, event: MemoryAuditEvent) -> str:
        self.audit_events.append(event)
        return event.event_id


class _FakeCoordinationBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def enqueue(self, kind: str, payload: dict[str, object]) -> bool:
        self.calls.append((kind, dict(payload)))
        return True


class _RecordingEmbeddingService:
    def __init__(self) -> None:
        self.calls: list[MemoryRecord] = []

    def ensure_embedding(self, record: MemoryRecord) -> None:
        self.calls.append(record)


def test_memory_write_enqueues_embedding_and_does_not_call_http_in_async_mode(
    monkeypatch,
) -> None:
    monkeypatch.delenv("FOCUS_AGENT_MEMORY_EMBED_ASYNC", raising=False)

    def fail_http_post(*args: Any, **kwargs: Any) -> httpx.Response:
        del args, kwargs
        raise AssertionError("async memory write must not call the embedding provider")

    monkeypatch.setattr(httpx.Client, "post", fail_http_post)
    repo = _FakeMemoryRepository()
    coordination_backend = _FakeCoordinationBackend()
    embedding_service = MemoryEmbeddingService(
        repository=repo,
        provider=OpenAICompatibleEmbeddingProvider(
            dimensions=3,
            api_key="test-key",
            base_url="https://embeddings.example.test/v1",
        ),
    )
    service = MemoryService(
        repository=repo,
        embedding_service=embedding_service,
        coordination_backend=coordination_backend,
    )

    memory_ids = service.write_records([_memory_request()])

    assert len(memory_ids) == 1
    memory_id = memory_ids[0]
    assert repo.records[memory_id].embedding_status == "pending"
    assert coordination_backend.calls == [
        (
            "memory_embedding",
            {
                "memory_id": memory_id,
                "namespace": list(user_profile_namespace("user-1")),
            },
        )
    ]


def test_memory_write_sync_flag_false_uses_embedding_service(monkeypatch) -> None:
    monkeypatch.setenv("FOCUS_AGENT_MEMORY_EMBED_ASYNC", "false")
    repo = _FakeMemoryRepository()
    coordination_backend = _FakeCoordinationBackend()
    embedding_service = _RecordingEmbeddingService()
    service = MemoryService(
        repository=repo,
        embedding_service=embedding_service,
        coordination_backend=coordination_backend,
    )

    memory_ids = service.write_records([_memory_request()])

    assert [record.memory_id for record in embedding_service.calls] == memory_ids
    assert coordination_backend.calls == []


def test_memory_write_falls_back_to_sync_embedding_without_enqueue_api(monkeypatch) -> None:
    monkeypatch.delenv("FOCUS_AGENT_MEMORY_EMBED_ASYNC", raising=False)
    repo = _FakeMemoryRepository()
    embedding_service = _RecordingEmbeddingService()
    service = MemoryService(
        repository=repo,
        embedding_service=embedding_service,
        coordination_backend=object(),
    )

    memory_ids = service.write_records([_memory_request()])

    assert [record.memory_id for record in embedding_service.calls] == memory_ids


def _memory_request() -> MemoryWriteRequest:
    return MemoryWriteRequest(
        kind=MemoryKind.USER_PREFERENCE,
        scope=MemoryScope.USER,
        visibility=MemoryVisibility.SHARED,
        namespace=user_profile_namespace("user-1"),
        content="Please keep answers concise.",
        summary="Concise answers",
        user_id="user-1",
        importance=0.8,
        semantic_key="pref-answer-style",
    )
