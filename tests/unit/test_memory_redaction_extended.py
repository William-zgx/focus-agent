from __future__ import annotations

import pytest

from focus_agent.memory.embedding_worker import MemoryEmbeddingWorker
from focus_agent.memory.models import (
    MemoryAuditEvent,
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
    MemoryVisibility,
    MemoryWriteRequest,
)
from focus_agent.memory.service import MemoryService, _redact_sensitive_text
from focus_agent.services.background_work import (
    BackgroundJobHandlerRegistry,
    DurableBackgroundWorker,
    register_default_background_job_handlers,
)
from focus_agent.services.coordination import BackgroundJobSpec, InMemoryBackgroundJobDeduperBackend
from focus_agent.storage.namespaces import project_memory_namespace


@pytest.mark.parametrize(
    ("family", "sample"),
    [
        ("github_pat", "token ghp_1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
        ("github_pat", "token gho_1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
        ("github_pat", "token ghu_1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
        ("aws_access_key", "aws key AKIA1234567890ABCDEF"),
        ("aws_access_key", "credential AKIAABCDEFGHIJKLMNOP"),
        ("jwt", "jwt eyJabc.DEF-ghi_123.JKL456_mno"),
        ("jwt", "bearer eyJ0eXAiOiJKV1Qi.XyZ_123-abc.signature_456"),
        ("password_url", "remote https://alice:hunter2@example.com/repo.git"),
        ("password_url", "mirror http://build:super-secret@git.example.test/path"),
    ],
)
def test_extended_sensitive_patterns_are_redacted(family: str, sample: str) -> None:
    redacted = _redact_sensitive_text(sample)

    assert "[redacted]" in redacted, family
    assert sample.split()[-1] not in redacted


def test_sensitive_memory_is_tagged_audited_and_not_embedded(monkeypatch) -> None:
    monkeypatch.setenv("FOCUS_AGENT_MEMORY_EMBED_ASYNC", "false")
    repo = _FakeMemoryRepository()
    embedding_service = _RecordingEmbeddingService()
    service = MemoryService(repository=repo, embedding_service=embedding_service)

    [memory_id] = service.write_records(
        [
            MemoryWriteRequest(
                kind=MemoryKind.PROJECT_FACT,
                scope=MemoryScope.PROJECT,
                visibility=MemoryVisibility.SHARED,
                namespace=project_memory_namespace("project-1"),
                content="Deploy key is AKIA1234567890ABCDEF",
                summary="Deploy key",
                importance=0.8,
                semantic_key="deploy-key",
            )
        ]
    )

    record = repo.records[memory_id]
    assert "redacted" in record.tags
    assert record.embedding_status == "failed"
    assert embedding_service.calls == []
    assert any(event.action == "redact_sensitive_content" for event in repo.audit_events)


def test_memory_embedding_worker_sets_ready_on_success() -> None:
    repo = _FakeMemoryRepository()
    record = _memory_record("memory-ready")
    repo.upsert_record(record)
    service = _RecordingEmbeddingService(result={"status": "written"})
    worker = MemoryEmbeddingWorker(repository=repo, embedding_service=service)

    worker.process_payload(memory_id=record.memory_id, namespace=record.namespace)

    assert service.calls == [record.memory_id]
    assert repo.records[record.memory_id].embedding_status == "ready"


def test_memory_embedding_worker_marks_failed_only_after_third_durable_failure() -> None:
    repo = _FakeMemoryRepository()
    record = _memory_record("memory-failed")
    repo.upsert_record(record)
    embedding_service = _FailingEmbeddingService()
    registry = BackgroundJobHandlerRegistry()
    register_default_background_job_handlers(
        registry,
        memory_embedding_service=embedding_service,
        memory_repository=repo,
    )
    backend = InMemoryBackgroundJobDeduperBackend(retry_base_delay_seconds=0.0)
    worker = DurableBackgroundWorker(name="memory-test", job_backend=backend, handlers=registry)

    assert backend.enqueue_job(
        BackgroundJobSpec(
            kind="memory_embedding",
            key=f"memory:memory_embedding:{record.memory_id}",
            payload={"memory_id": record.memory_id, "namespace": list(record.namespace)},
            max_attempts=3,
            dedupe_policy="replace",
        )
    )
    assert worker.run_once()
    assert repo.records[record.memory_id].embedding_status == "pending"
    assert worker.run_once()
    assert repo.records[record.memory_id].embedding_status == "pending"
    assert worker.run_once()

    assert repo.records[record.memory_id].embedding_status == "failed"
    assert embedding_service.calls == [record.memory_id, record.memory_id, record.memory_id]
    assert any(event.action == "embedding_failed" for event in repo.audit_events)


class _FakeMemoryRepository:
    def __init__(self) -> None:
        self.records: dict[str, MemoryRecord] = {}
        self.audit_events: list[MemoryAuditEvent] = []

    def upsert_record(self, record: MemoryRecord) -> str:
        self.records[record.memory_id] = record
        return record.memory_id

    def get_record(self, memory_id: str) -> MemoryRecord | None:
        return self.records.get(memory_id)

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


class _RecordingEmbeddingService:
    def __init__(self, *, result: dict[str, object] | None = None) -> None:
        self.calls: list[str] = []
        self.result = result or {"status": "written"}
        self.provider = None

    def ensure_embedding(self, record: MemoryRecord) -> dict[str, object]:
        self.calls.append(record.memory_id)
        return dict(self.result)


class _FailingEmbeddingService(_RecordingEmbeddingService):
    def ensure_embedding(self, record: MemoryRecord) -> dict[str, object]:
        self.calls.append(record.memory_id)
        raise RuntimeError("embedding backend unavailable")


def _memory_record(memory_id: str) -> MemoryRecord:
    return MemoryRecord(
        memory_id=memory_id,
        kind=MemoryKind.PROJECT_FACT,
        scope=MemoryScope.PROJECT,
        visibility=MemoryVisibility.SHARED,
        status=MemoryStatus.ACTIVE,
        namespace=project_memory_namespace("project-1"),
        content="Project deploys from the release branch.",
        summary="Deploys from release branch",
        semantic_key=f"{memory_id}-semantic",
    )
