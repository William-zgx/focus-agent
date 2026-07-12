from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from focus_agent.memory.embedding_worker import MemoryEmbeddingWorker
from focus_agent.memory.models import (
    MemoryAuditEvent,
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
    MemoryVisibility,
)
from focus_agent.migrations.local import applier
from focus_agent.migrations.local.loader import LocalStoreItemRecord
from focus_agent.repositories.postgres_memory_repository import PostgresMemoryRepository


class _RecordingCursor:
    def __init__(self, *, rowcount: int = 1, rows: list[dict[str, object]] | None = None) -> None:
        self.statements: list[tuple[str, object]] = []
        self.rowcount = rowcount
        self._rows = list(rows or [])

    def __enter__(self) -> _RecordingCursor:
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        return False

    def execute(self, sql: str, params: object = None) -> None:
        self.statements.append((" ".join(sql.split()), params))

    def fetchall(self) -> list[dict[str, object]]:
        return list(self._rows)


class _RecordingConnection:
    def __init__(self, cursor: _RecordingCursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> _RecordingConnection:
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        return False

    def cursor(self) -> _RecordingCursor:
        return self._cursor


def test_postgres_upsert_sql_cannot_overwrite_forgotten_or_tombstoned_memory(
    monkeypatch,
) -> None:
    cursor = _RecordingCursor()
    monkeypatch.setattr(
        "focus_agent.repositories.postgres_memory_repository.psycopg.connect",
        lambda uri, row_factory=None: _RecordingConnection(cursor),
    )
    repository = PostgresMemoryRepository("postgresql://example")

    repository.upsert_record(_memory_record("memory-protected"))

    sql, _params = cursor.statements[-1]
    assert "NOT EXISTS ( SELECT 1 FROM focus_memory_tombstones" in sql
    assert "focus_memories.status <> 'forgotten'" in sql
    assert "focus_memories.deleted_at IS NULL" in sql

    cursor.rowcount = 0
    assert not repository.upsert_record_if_not_tombstoned(_memory_record("memory-protected"))


def test_postgres_embedding_status_update_is_conditional_and_field_scoped(
    monkeypatch,
) -> None:
    cursor = _RecordingCursor(rowcount=1)
    monkeypatch.setattr(
        "focus_agent.repositories.postgres_memory_repository.psycopg.connect",
        lambda uri, row_factory=None: _RecordingConnection(cursor),
    )
    repository = PostgresMemoryRepository("postgresql://example")

    assert repository.update_record_embedding_status(
        memory_id="memory-active",
        status="ready",
        model_id="embedding-model",
        updated_at=datetime.now(UTC),
    )

    sql, params = cursor.statements[-1]
    update_clause, where_clause = sql.split(" WHERE ", maxsplit=1)
    assert "embedding_status" in update_clause
    assert "data_json = data_json || %(embedding_payload)s" in update_clause
    assert "content =" not in update_clause
    assert "summary =" not in update_clause
    assert " SET status =" not in update_clause
    assert ", status =" not in update_clause
    assert "deleted_at =" not in update_clause
    assert "status <> 'forgotten'" in where_clause
    assert "deleted_at IS NULL" in where_clause
    assert "focus_memory_tombstones" in where_clause
    assert params is not None
    embedding_payload = params["embedding_payload"].obj
    assert embedding_payload == {
        "embedding_status": "ready",
        "embedding_model_id": "embedding-model",
        "embedding_updated_at": embedding_payload["embedding_updated_at"],
        "updated_at": embedding_payload["updated_at"],
    }


def test_embedding_worker_stale_copy_cannot_revive_concurrently_forgotten_memory() -> None:
    repository = _ConcurrentMemoryRepository(_memory_record("memory-race"))
    embedding_service = _RacingEmbeddingService(repository)
    worker = MemoryEmbeddingWorker(
        repository=repository,
        embedding_service=embedding_service,
    )

    worker.process_payload(
        memory_id="memory-race",
        namespace=repository.record.namespace,
    )

    assert repository.record.status == MemoryStatus.FORGOTTEN
    assert repository.record.content == ""
    assert repository.record.summary == "[forgotten]"
    assert repository.record.deleted_at is not None
    assert repository.full_upserts == []
    assert repository.conditional_updates == [("memory-race", "ready", "embedding-model")]
    assert repository.deleted_embedding_ids == ["memory-race"]


def test_embedding_worker_does_not_embed_already_forgotten_memory() -> None:
    forgotten_at = datetime.now(UTC)
    forgotten = _memory_record("memory-forgotten").model_copy(
        update={
            "status": MemoryStatus.FORGOTTEN,
            "content": "",
            "summary": "[forgotten]",
            "deleted_at": forgotten_at,
        }
    )
    repository = _ConcurrentMemoryRepository(forgotten)
    embedding_service = _RecordingEmbeddingService()
    worker = MemoryEmbeddingWorker(
        repository=repository,
        embedding_service=embedding_service,
    )

    worker.process_payload(
        memory_id=forgotten.memory_id,
        namespace=forgotten.namespace,
    )

    assert embedding_service.calls == []
    assert repository.full_upserts == []
    assert repository.conditional_updates == []


def test_embedding_worker_preserves_active_record_during_conditional_status_update() -> None:
    original = _memory_record("memory-active")
    repository = _ConcurrentMemoryRepository(original)
    embedding_service = _RecordingEmbeddingService()
    worker = MemoryEmbeddingWorker(
        repository=repository,
        embedding_service=embedding_service,
    )

    worker.process_payload(
        memory_id=original.memory_id,
        namespace=original.namespace,
    )

    assert repository.record.content == original.content
    assert repository.record.summary == original.summary
    assert repository.record.status == MemoryStatus.ACTIVE
    assert repository.record.deleted_at is None
    assert repository.record.embedding_status == "ready"
    assert repository.full_upserts == []
    assert repository.conditional_updates == [("memory-active", "ready", "embedding-model")]
    assert repository.deleted_embedding_ids == []


def test_local_memory_migration_skips_tombstoned_ids_and_migrates_active_ids(
    monkeypatch,
) -> None:
    repository = _MigrationMemoryRepository(tombstoned_ids={"memory-forgotten"})
    monkeypatch.setattr(
        applier,
        "create_memory_repository",
        lambda _database_uri: repository,
    )
    items = [
        _local_memory_item("memory-forgotten", "forgotten source content"),
        _local_memory_item("memory-active", "active source content"),
    ]

    result = applier._migrate_focus_memories(
        "postgresql://example",
        items,
        dry_run=False,
    )

    assert set(repository.atomic_upsert_ids) == {"memory-forgotten", "memory-active"}
    assert [record.memory_id for record in repository.upserted] == ["memory-active"]
    assert result["migrated_memory_count"] == 1
    assert result["eligible_memory_count"] == 1
    assert result["skipped_item_count"] == 1
    assert result["skipped_reasons"] == {"tombstoned_memory_id": 1}
    assert result["tombstoned_memory_count"] == 1


class _ConcurrentMemoryRepository:
    def __init__(self, record: MemoryRecord) -> None:
        self.record = record
        self.full_upserts: list[MemoryRecord] = []
        self.conditional_updates: list[tuple[str, str, str | None]] = []
        self.deleted_embedding_ids: list[str] = []
        self.audit_events: list[MemoryAuditEvent] = []

    def get_record(self, memory_id: str) -> MemoryRecord | None:
        return self.record if self.record.memory_id == memory_id else None

    def upsert_record(self, record: MemoryRecord) -> str:
        self.full_upserts.append(record)
        self.record = record
        return record.memory_id

    def update_record_embedding_status(
        self,
        *,
        memory_id: str,
        status: str,
        model_id: str | None,
        updated_at: datetime,
    ) -> bool:
        self.conditional_updates.append((memory_id, status, model_id))
        if (
            self.record.memory_id != memory_id
            or self.record.status == MemoryStatus.FORGOTTEN
            or self.record.deleted_at is not None
        ):
            return False
        self.record = self.record.model_copy(
            update={
                "embedding_status": status,
                "embedding_model_id": model_id,
                "embedding_updated_at": updated_at,
                "updated_at": updated_at,
            }
        )
        return True

    def delete_embedding(self, memory_id: str) -> bool:
        self.deleted_embedding_ids.append(memory_id)
        return True

    def append_audit_event(self, event: MemoryAuditEvent) -> str:
        self.audit_events.append(event)
        return event.event_id

    def forget_during_embedding(self) -> None:
        now = datetime.now(UTC)
        self.record = self.record.model_copy(
            update={
                "status": MemoryStatus.FORGOTTEN,
                "content": "",
                "summary": "[forgotten]",
                "deleted_at": now,
                "updated_at": now,
            }
        )


class _RecordingEmbeddingService:
    provider = SimpleNamespace(model_id="embedding-model")

    def __init__(self) -> None:
        self.calls: list[str] = []

    def ensure_embedding(self, record: MemoryRecord) -> dict[str, str]:
        self.calls.append(record.memory_id)
        return {"status": "written"}


class _RacingEmbeddingService(_RecordingEmbeddingService):
    def __init__(self, repository: _ConcurrentMemoryRepository) -> None:
        super().__init__()
        self.repository = repository

    def ensure_embedding(self, record: MemoryRecord) -> dict[str, str]:
        self.calls.append(record.memory_id)
        self.repository.forget_during_embedding()
        return {"status": "written"}


class _MigrationMemoryRepository:
    def __init__(self, *, tombstoned_ids: set[str]) -> None:
        self.tombstoned_ids = set(tombstoned_ids)
        self.atomic_upsert_ids: list[str] = []
        self.upserted: list[MemoryRecord] = []

    def upsert_record_if_not_tombstoned(self, record: MemoryRecord) -> bool:
        self.atomic_upsert_ids.append(record.memory_id)
        if record.memory_id in self.tombstoned_ids:
            return False
        self.upserted.append(record)
        return True

    def upsert_record(self, record: MemoryRecord) -> str:
        self.upserted.append(record)
        return record.memory_id


def _memory_record(memory_id: str) -> MemoryRecord:
    return MemoryRecord(
        memory_id=memory_id,
        kind=MemoryKind.PROJECT_FACT,
        scope=MemoryScope.PROJECT,
        visibility=MemoryVisibility.SHARED,
        status=MemoryStatus.ACTIVE,
        namespace=("project", "project-1"),
        content=f"content for {memory_id}",
        summary=f"summary for {memory_id}",
        semantic_key=f"semantic:{memory_id}",
    )


def _local_memory_item(memory_id: str, content: str) -> LocalStoreItemRecord:
    return LocalStoreItemRecord(
        namespace=("project", "project-1"),
        key=memory_id,
        value={
            "memory_id": memory_id,
            "kind": MemoryKind.PROJECT_FACT.value,
            "content": content,
            "summary": content,
        },
        created_at=None,
        updated_at=None,
    )
