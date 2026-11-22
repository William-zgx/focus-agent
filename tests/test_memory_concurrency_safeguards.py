from __future__ import annotations

import threading
from datetime import UTC, datetime

import pytest
from psycopg.errors import UniqueViolation

from focus_agent.core.request_context import RequestContext
from focus_agent.core.types import PromptMode
from focus_agent.memory.dedupe import merge_duplicate_records
from focus_agent.memory.embedding import MemoryEmbeddingService
from focus_agent.memory.embedding_cleanup import (
    MemoryEmbeddingCleanupError,
    delete_embedding_artifacts,
)
from focus_agent.memory.embedding_providers import DeterministicTestEmbeddingProvider
from focus_agent.memory.embedding_worker import MemoryEmbeddingWorker
from focus_agent.memory.models import (
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
    MemoryVisibility,
    MemoryWriteDecisionStatus,
    MemoryWriteRequest,
)
from focus_agent.memory.retriever import MemoryRetriever
from focus_agent.memory.service import MemoryService
from focus_agent.repositories.memory_repository import (
    MemoryMutationResult,
    MemoryRecordProtectedError,
    MemoryRecordStaleError,
)
from focus_agent.repositories.postgres_memory_repository import PostgresMemoryRepository
from focus_agent.retrieval import InMemoryRetrievalIndex
from focus_agent.storage.namespaces import project_memory_namespace

from .test_memory_service import _FakeMemoryRepository


def _request(content: str, *, importance: float = 0.5) -> MemoryWriteRequest:
    return MemoryWriteRequest(
        kind=MemoryKind.PROJECT_FACT,
        scope=MemoryScope.PROJECT,
        visibility=MemoryVisibility.SHARED,
        namespace=project_memory_namespace("project-1"),
        content=content,
        summary=content,
        user_id="user-1",
        root_thread_id="root-1",
        semantic_key="release-decision",
        importance=importance,
    )


def test_stale_merge_returns_conflict_after_bounded_retries():
    class StaleRepository(_FakeMemoryRepository):
        def update_record_if_current(self, _record, *, expected_updated_at):
            assert expected_updated_at is not None
            return MemoryMutationResult.STALE

    repository = StaleRepository()
    service = MemoryService(repository=repository)
    service.upsert_request(_request("release decision OLD"))

    result = service.upsert_request(_request("release decision NEW", importance=0.9))

    assert result.status == MemoryWriteDecisionStatus.CONFLICT
    assert result.action == "stale_revision"
    assert next(iter(repository.records.values())).content == "release decision OLD"


def test_stale_merge_retries_with_fresh_revision():
    class RetryOnceRepository(_FakeMemoryRepository):
        def __init__(self) -> None:
            super().__init__()
            self.mutation_calls = 0

        def update_record_if_current(self, record, *, expected_updated_at):
            self.mutation_calls += 1
            if self.mutation_calls == 1:
                return MemoryMutationResult.STALE
            return super().update_record_if_current(
                record,
                expected_updated_at=expected_updated_at,
            )

    repository = RetryOnceRepository()
    service = MemoryService(repository=repository)
    first = service.upsert_request(_request("release decision OLD"))

    result = service.upsert_request(_request("release decision NEW", importance=0.9))

    assert result.status == MemoryWriteDecisionStatus.MERGED
    assert result.memory_id == first.memory_id
    assert repository.mutation_calls == 2
    assert repository.records[first.memory_id].content == "release decision NEW"


def test_legacy_repository_merge_remains_compatible_but_postgres_requires_revision_checks():
    class WithoutRevisionRepository(_FakeMemoryRepository):
        update_record_if_current = None

    repository = WithoutRevisionRepository()
    service = MemoryService(repository=repository)
    service.upsert_request(_request("release decision OLD"))

    result = service.upsert_request(_request("release decision NEW", importance=0.9))

    assert result.status == MemoryWriteDecisionStatus.MERGED
    assert next(iter(repository.records.values())).content == "release decision NEW"
    assert callable(PostgresMemoryRepository.update_record_if_current)


class _EmbeddingStatusRepository(_FakeMemoryRepository):
    def __init__(self, *, accept_update: bool = True) -> None:
        super().__init__()
        self.accept_update = accept_update
        self.deleted_embedding_ids: list[str] = []

    def update_record_embedding_status(
        self,
        *,
        memory_id: str,
        status: str,
        model_id: str | None,
        updated_at: datetime,
        expected_fingerprint: str | None = None,
    ) -> bool:
        if not self.accept_update:
            return False
        return super().update_record_embedding_status(
            memory_id=memory_id,
            status=status,
            model_id=model_id,
            updated_at=updated_at,
            expected_fingerprint=expected_fingerprint,
        )

    def delete_embedding(self, memory_id: str) -> bool:
        self.deleted_embedding_ids.append(memory_id)
        return True


class _BlockingEmbedding:
    def __init__(self) -> None:
        self.provider = type("Provider", (), {"model_id": "test-embedding"})()
        self.read = threading.Event()
        self.release = threading.Event()

    def ensure_embedding(self, _record):
        self.read.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("test did not release embedding")
        return {"status": "written"}


def test_stale_embedding_completion_does_not_overwrite_newer_merge(monkeypatch):
    monkeypatch.setenv("FOCUS_AGENT_MEMORY_EMBED_ASYNC", "false")
    repository = _EmbeddingStatusRepository()
    embedding = _BlockingEmbedding()
    service = MemoryService(repository=repository, embedding_service=embedding)
    worker_errors: list[BaseException] = []

    def write() -> None:
        try:
            service.upsert_request(_request("release decision OLD"))
        except BaseException as exc:  # noqa: BLE001
            worker_errors.append(exc)

    thread = threading.Thread(target=write)
    thread.start()
    assert embedding.read.wait(timeout=5)
    memory_id = next(iter(repository.records))
    repository.records[memory_id] = merge_duplicate_records(
        repository.records[memory_id],
        _request("release decision NEWER", importance=0.9),
    )
    embedding.release.set()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert worker_errors == []
    assert repository.records[memory_id].content == "release decision NEWER"
    assert repository.records[memory_id].embedding_status == "pending"
    assert repository.deleted_embedding_ids == []


class _SuccessfulEmbedding:
    provider = type("Provider", (), {"model_id": "test-embedding"})()

    def __init__(self, result=None) -> None:
        self.result = result or {"status": "written"}

    def ensure_embedding(self, _record):
        return dict(self.result)


def test_rejected_embedding_status_deletes_late_embedding(monkeypatch):
    monkeypatch.setenv("FOCUS_AGENT_MEMORY_EMBED_ASYNC", "false")
    repository = _EmbeddingStatusRepository(accept_update=False)
    record = MemoryRecord(
        memory_id="memory-late-embedding",
        kind=MemoryKind.PROJECT_FACT,
        scope=MemoryScope.PROJECT,
        visibility=MemoryVisibility.SHARED,
        namespace=project_memory_namespace("project-1"),
        content="release decision OLD",
        summary="release decision OLD",
        semantic_key="release-decision",
    )
    repository.upsert_record(
        record.model_copy(
            update={
                "status": MemoryStatus.FORGOTTEN,
                "deleted_at": datetime.now(UTC),
            }
        )
    )
    service = MemoryService(repository=repository, embedding_service=_SuccessfulEmbedding())

    service._write_embedding_best_effort(record)

    assert repository.deleted_embedding_ids == [record.memory_id]


def test_embedding_service_rejection_removes_index_and_embedding():
    class ProtectedRepository(_EmbeddingStatusRepository):
        def upsert_memory_embedding(self, *_args, **_kwargs):
            raise MemoryRecordProtectedError("memory-late-embedding")

    repository = ProtectedRepository()
    record = MemoryRecord(
        memory_id="memory-late-embedding",
        kind=MemoryKind.PROJECT_FACT,
        scope=MemoryScope.PROJECT,
        visibility=MemoryVisibility.SHARED,
        namespace=project_memory_namespace("project-1"),
        content="release decision OLD",
        summary="release decision OLD",
        semantic_key="release-decision",
    )
    repository.upsert_record(record)
    index = InMemoryRetrievalIndex()
    service = MemoryEmbeddingService(
        repository=repository,
        provider=DeterministicTestEmbeddingProvider(dimensions=3),
        retrieval_index=index,
    )

    result = service.ensure_embedding(record)

    assert result["status"] == "rejected"
    assert result["reason"] == "memory_protected"
    assert repository.deleted_embedding_ids == [record.memory_id]
    assert index.search(collection="focus_memory", query="release", limit=5, filters={}) == []


def test_unique_violation_during_first_write_retries_as_merge():
    class UniqueOnceRepository(_FakeMemoryRepository):
        def __init__(self) -> None:
            super().__init__()
            self.raise_once = True

        def upsert_record(self, record):
            result = super().upsert_record(record)
            if self.raise_once:
                self.raise_once = False
                raise UniqueViolation
            return result

    repository = UniqueOnceRepository()
    service = MemoryService(repository=repository)

    result = service.upsert_request(_request("release decision OLD"))

    assert result.status == MemoryWriteDecisionStatus.MERGED
    assert len(repository.records) == 1


def test_null_fingerprint_record_is_retrievable_after_embedding():
    class WritableEmbeddingRepository(_EmbeddingStatusRepository):
        def upsert_memory_embedding(self, memory_id, **_kwargs):
            return memory_id

    repository = WritableEmbeddingRepository()
    record = MemoryRecord(
        memory_id="memory-null-fingerprint-retrieval",
        kind=MemoryKind.PROJECT_FACT,
        scope=MemoryScope.PROJECT,
        visibility=MemoryVisibility.SHARED,
        namespace=project_memory_namespace("project-1"),
        content="release decision OLD",
        summary="release decision OLD",
        semantic_key="release-decision",
        fingerprint=None,
    )
    repository.upsert_record(record)
    index = InMemoryRetrievalIndex()
    embedding = MemoryEmbeddingService(
        repository=repository,
        provider=DeterministicTestEmbeddingProvider(dimensions=3),
        retrieval_index=index,
    )
    assert embedding.ensure_embedding(record)["status"] == "written"

    bundle = MemoryRetriever(repository=repository, retrieval_index=index).retrieve_for_turn(
        context=RequestContext(user_id="user-1", root_thread_id="root-1", project_id="project-1"),
        state={},
        query="release decision",
        prompt_mode=PromptMode.EXPLORE,
    )

    assert [hit.record.memory_id for hit in bundle.hits] == [record.memory_id]
    assert bundle.retrieval_plan["source"] == "zvec"


def test_stale_merge_does_not_recreate_forgotten_memory_with_new_id():
    class StaleThenForgetRepository(_FakeMemoryRepository):
        def update_record_if_current(self, _record, *, expected_updated_at):
            for record in list(self.records.values()):
                self.forget_record(memory_id=record.memory_id)
            return MemoryMutationResult.STALE

    repository = StaleThenForgetRepository()
    service = MemoryService(repository=repository)
    service.upsert_request(_request("release decision OLD"))

    result = service.upsert_request(_request("release decision NEW", importance=0.9))

    assert result.status == MemoryWriteDecisionStatus.SKIPPED
    assert result.action == "protected"
    assert result.memory_id is None


def test_worker_stale_result_raises_for_durable_retry():
    repository = _EmbeddingStatusRepository()
    record = MemoryRecord(
        memory_id="memory-stale-worker",
        kind=MemoryKind.PROJECT_FACT,
        scope=MemoryScope.PROJECT,
        visibility=MemoryVisibility.SHARED,
        namespace=project_memory_namespace("project-1"),
        content="release decision OLD",
        summary="release decision OLD",
        semantic_key="release-decision",
    )
    repository.upsert_record(record)
    worker = MemoryEmbeddingWorker(
        repository=repository,
        embedding_service=_SuccessfulEmbedding(),
    )
    worker.embedding_service.result = {"status": "stale"}

    with pytest.raises(MemoryRecordStaleError):
        worker.process_payload(memory_id=record.memory_id, namespace=record.namespace)


def test_cleanup_attempts_both_backends_before_raising():
    repository = _EmbeddingStatusRepository()

    class FailingIndex:
        def delete(self, **_kwargs):
            raise RuntimeError("index unavailable")

    with pytest.raises(MemoryEmbeddingCleanupError):
        delete_embedding_artifacts(
            repository,
            "memory-late-embedding",
            retrieval_index=FailingIndex(),
        )

    assert repository.deleted_embedding_ids == ["memory-late-embedding"]
