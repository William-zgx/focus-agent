from __future__ import annotations

import os
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import psycopg
import pytest

from focus_agent.memory.embedding import MemoryEmbeddingService
from focus_agent.memory.embedding_providers import DeterministicTestEmbeddingProvider
from focus_agent.memory.embedding_repository_adapter import MemoryEmbeddingPayload
from focus_agent.memory.models import (
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
    MemoryVisibility,
)
from focus_agent.memory.service import MemoryService
from focus_agent.repositories.memory_repository import (
    MemoryMutationResult,
    MemoryRecordProtectedError,
    MemoryRecordStaleError,
)
from focus_agent.repositories.postgres_memory_repository import PostgresMemoryRepository
from focus_agent.retrieval import InMemoryRetrievalIndex
from focus_agent.storage.namespaces import project_memory_namespace


def _require_database_uri() -> str:
    database_uri = os.environ.get("DATABASE_URI")
    if database_uri:
        return database_uri
    if os.environ.get("FOCUS_AGENT_REQUIRE_REAL_POSTGRES") == "1":
        raise RuntimeError("DATABASE_URI is required for real Postgres mutation tests")
    pytest.skip("DATABASE_URI is required for real Postgres mutation tests")


def _scoped_database_uri(database_uri: str, schema: str) -> str:
    parts = urlsplit(database_uri)
    query = parse_qsl(parts.query)
    query.append(("options", f"-c search_path={schema},public"))
    return urlunsplit(parts._replace(query=urlencode(query, quote_via=quote)))


@contextmanager
def _isolated_schema(database_uri: str):
    schema = f"t_{uuid.uuid4().hex}"
    with psycopg.connect(database_uri, autocommit=True) as connection:
        connection.execute("CREATE EXTENSION IF NOT EXISTS vector SCHEMA public")
        connection.execute(f'CREATE SCHEMA "{schema}"')
    try:
        yield _scoped_database_uri(database_uri, schema)
    finally:
        with psycopg.connect(database_uri, autocommit=True) as connection:
            connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def _repository(database_uri: str) -> PostgresMemoryRepository:
    repository = PostgresMemoryRepository(
        database_uri,
        dimensions=3,
        memory_embeddings_enabled=True,
        pgvector_extension_mode="required",
    )
    repository.setup()
    return repository


def _record(memory_id: str) -> MemoryRecord:
    return MemoryRecord(
        memory_id=memory_id,
        kind=MemoryKind.PROJECT_FACT,
        scope=MemoryScope.PROJECT,
        visibility=MemoryVisibility.SHARED,
        namespace=project_memory_namespace(f"project-{memory_id}"),
        content="synthetic old decision",
        summary="synthetic old decision",
        semantic_key=f"semantic:{memory_id}",
    )


def test_isolated_schema_options_use_libpq_space_encoding():
    scoped_uri = _scoped_database_uri("postgresql://example/db", "t_example")

    assert "options=-c%20search_path%3Dt_example%2Cpublic" in scoped_uri
    assert "options=-c+search_path" not in scoped_uri


def test_update_record_if_current_distinguishes_stale_and_protected():
    with _isolated_schema(_require_database_uri()) as database_uri:
        repository = _repository(database_uri)
        original = _record(f"memory-revision-{uuid.uuid4().hex}")
        repository.upsert_record(original)
        current = repository.get_record(original.memory_id)
        assert current is not None
        updated = current.model_copy(
            update={
                "content": "synthetic current decision",
                "summary": "synthetic current decision",
                "updated_at": datetime.now(UTC),
            }
        )

        assert (
            repository.update_record_if_current(
                updated,
                expected_updated_at=current.updated_at,
            )
            == MemoryMutationResult.APPLIED
        )
        stale = updated.model_copy(
            update={"content": "stale overwrite", "summary": "stale overwrite"}
        )
        assert (
            repository.update_record_if_current(
                stale,
                expected_updated_at=current.updated_at,
            )
            == MemoryMutationResult.STALE
        )
        assert repository.get_record(original.memory_id).content == "synthetic current decision"

        repository.forget_record(memory_id=original.memory_id, namespace=original.namespace)
        assert (
            repository.update_record_if_current(
                stale,
                expected_updated_at=updated.updated_at,
            )
            == MemoryMutationResult.PROTECTED
        )


def test_stale_embedding_cannot_replace_current_revision_vector():
    with _isolated_schema(_require_database_uri()) as database_uri:
        repository = _repository(database_uri)
        original = _record(f"memory-stale-vector-{uuid.uuid4().hex}")
        original = original.model_copy(update={"fingerprint": "old-fingerprint"})
        repository.upsert_record(original)
        updated = original.model_copy(
            update={
                "content": "synthetic current decision",
                "summary": "synthetic current decision",
                "fingerprint": "new-fingerprint",
                "updated_at": datetime.now(UTC),
            }
        )
        assert (
            repository.update_record_if_current(
                updated,
                expected_updated_at=original.updated_at,
            )
            == MemoryMutationResult.APPLIED
        )
        repository.upsert_embedding(
            memory_id=original.memory_id,
            namespace=original.namespace,
            embedding=[0.1, 0.2, 0.3],
            provider_id="deterministic-test",
            model_id="deterministic-test",
            content_hash="v2",
            expected_fingerprint="new-fingerprint",
        )

        with pytest.raises(MemoryRecordStaleError):
            repository.upsert_memory_embedding(
                MemoryEmbeddingPayload(
                    memory_id=original.memory_id,
                    namespace=original.namespace,
                    provider_id="deterministic-test",
                    model_id="deterministic-test",
                    dimensions=3,
                    content_hash="v1",
                    embedding=[0.3, 0.2, 0.1],
                    metadata={},
                    fingerprint="old-fingerprint",
                )
            )

        current = repository.get_memory_embedding(original.memory_id)
        assert current is not None
        assert current.content_hash == "v2"


def test_null_fingerprint_legacy_record_can_embed_and_mark_ready():
    with _isolated_schema(_require_database_uri()) as database_uri:
        repository = _repository(database_uri)
        record = _record(f"memory-null-fingerprint-{uuid.uuid4().hex}")
        record = record.model_copy(update={"fingerprint": None})
        repository.upsert_record(record)
        service = MemoryEmbeddingService(
            repository=repository,
            provider=DeterministicTestEmbeddingProvider(dimensions=3),
        )

        result = service.ensure_embedding(record)
        assert result["status"] == "written"
        assert repository.get_memory_embedding(record.memory_id) is not None
        assert (
            repository.update_record_embedding_status(
                memory_id=record.memory_id,
                status="ready",
                model_id="deterministic-test",
                updated_at=datetime.now(UTC),
                expected_fingerprint="computed-but-nullable-parent",
            )
            is True
        )
        assert repository.get_record(record.memory_id).embedding_status == "ready"


def test_forget_rejects_late_embedding_and_removes_retrieval_document(monkeypatch):
    monkeypatch.setenv("FOCUS_AGENT_MEMORY_EMBED_ASYNC", "false")
    with _isolated_schema(_require_database_uri()) as database_uri:
        repository = _repository(database_uri)
        record = _record(f"memory-embedding-race-{uuid.uuid4().hex}")
        repository.upsert_record(record)
        provider = DeterministicTestEmbeddingProvider(dimensions=3)
        read = threading.Event()
        release = threading.Event()
        original_embed = provider.embed_texts

        def blocking_embed(texts):
            read.set()
            if not release.wait(timeout=10):
                raise TimeoutError("test did not release embedding")
            return original_embed(texts)

        provider.embed_texts = blocking_embed
        retrieval_index = InMemoryRetrievalIndex()
        embedding = MemoryEmbeddingService(
            repository=repository,
            provider=provider,
            retrieval_index=retrieval_index,
        )
        service = MemoryService(
            repository=repository,
            embedding_service=embedding,
            retrieval_index=retrieval_index,
        )
        worker_errors: list[BaseException] = []

        def run() -> None:
            try:
                service._write_embedding_best_effort(record)
            except BaseException as exc:  # noqa: BLE001
                worker_errors.append(exc)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        try:
            assert read.wait(timeout=10)
            tombstone_id = repository.forget_record(
                memory_id=record.memory_id,
                namespace=record.namespace,
            )
            assert tombstone_id is not None
        finally:
            release.set()
            thread.join(timeout=10)

        assert not thread.is_alive()
        assert worker_errors == []
        stored = repository.get_record(record.memory_id)
        assert stored is not None
        assert stored.status == MemoryStatus.FORGOTTEN
        assert stored.content == ""
        assert repository.get_memory_embedding(record.memory_id) is None
        assert (
            retrieval_index.search(
                collection="focus_memory",
                query="synthetic",
                limit=5,
                filters={},
            )
            == []
        )
        with pytest.raises(MemoryRecordProtectedError):
            repository.upsert_embedding(
                memory_id=record.memory_id,
                namespace=record.namespace,
                embedding=[0.1, 0.2, 0.3],
                provider_id="deterministic-test",
                model_id="deterministic-test",
            )
