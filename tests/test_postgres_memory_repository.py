from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from focus_agent.memory.models import (
    MemoryAuditEvent,
    MemoryCandidate,
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
    MemoryVisibility,
    MemoryWriteDecisionStatus,
    MemoryWriteRequest,
)
from focus_agent.repositories.memory_repository import MemoryEmbeddingListQuery, MemoryListQuery
from focus_agent.repositories.postgres_memory_repository import PostgresMemoryRepository
from focus_agent.repositories.postgres_schema import (
    SCHEMA_VERSION,
    _MIGRATIONS,
    _run_migration_v10,
    rebuild_memory_embedding_index_on_connection,
)


class _FakePostgresMemoryDB:
    def __init__(self) -> None:
        self.memories: dict[str, dict[str, Any]] = {}
        self.audit_events: dict[str, dict[str, Any]] = {}
        self.tombstones: dict[str, dict[str, Any]] = {}
        self.candidates: dict[str, dict[str, Any]] = {}
        self.embeddings: dict[str, dict[str, Any]] = {}


class _FakeCursor:
    def __init__(self, db: _FakePostgresMemoryDB) -> None:
        self.db = db
        self._fetchone: dict[str, Any] | None = None
        self._fetchall: list[dict[str, Any]] = []
        self.rowcount = 0

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute(self, sql: str, params=None) -> None:  # noqa: C901, PLR0912
        normalized = " ".join(sql.split())
        self._fetchone = None
        self._fetchall = []
        self.rowcount = 0
        if normalized.startswith("INSERT INTO focus_memories"):
            payload = _json_payload(params["data_json"])
            row = dict(params)
            row["data_json"] = payload
            self.db.memories[str(params["memory_id"])] = row
            return
        if normalized.startswith("SELECT data_json FROM focus_memories WHERE memory_id = %s"):
            row = self.db.memories.get(str(params[0]))
            self._fetchone = {"data_json": row["data_json"]} if row else None
            return
        if normalized.startswith("SELECT data_json FROM focus_memories") and "fingerprint" in normalized:
            matches = [
                row
                for row in self.db.memories.values()
                if row["namespace"] == params["namespace"]
                and row["status"] != MemoryStatus.FORGOTTEN.value
                and row["deleted_at"] is None
                and (row["fingerprint"] == params["fingerprint"] or row["semantic_key"] == params["semantic_key"])
                and (not params.get("kind") or row["kind"] == params["kind"])
                and (not params.get("scope") or row["scope"] == params["scope"])
            ]
            matches.sort(key=lambda row: row["updated_at"], reverse=True)
            self._fetchone = {"data_json": matches[0]["data_json"]} if matches else None
            return
        if normalized.startswith("SELECT data_json, CASE"):
            query = str(params["query"] or "").casefold()
            rows = [
                row
                for row in self.db.memories.values()
                if row["namespace"] == params["namespace"]
                and row["status"] == MemoryStatus.ACTIVE.value
                and row["deleted_at"] is None
                and _matches_query(row, query)
            ]
            rows.sort(key=lambda row: (row["importance"], row["updated_at"]), reverse=True)
            self._fetchall = [
                {
                    "data_json": row["data_json"],
                    "text_score": 1.0 if query else 0.0,
                }
                for row in rows[: int(params["limit"])]
            ]
            return
        if normalized.startswith("SELECT data_json FROM focus_memories"):
            rows = [
                row
                for row in self.db.memories.values()
                if (
                    row["deleted_at"] is None
                    or params.get("status") == MemoryStatus.FORGOTTEN.value
                )
                and _memory_row_matches_list_query(row, params)
            ]
            rows.sort(key=lambda row: (row["updated_at"], row["memory_id"]), reverse=True)
            offset = int(params["offset"])
            limit = int(params["limit"])
            self._fetchall = [
                {"data_json": row["data_json"]}
                for row in rows[offset : offset + limit]
            ]
            return
        if normalized.startswith("INSERT INTO focus_memory_embeddings"):
            memory_id = str(params["memory_id"])
            embedding_id = str(params["embedding_id"])
            previous = self.db.embeddings.get(embedding_id)
            row = dict(params)
            row["namespace"] = list(params["namespace"])
            row["embedding"] = _parse_vector_literal(params["embedding"])
            row["metadata_json"] = _json_payload(params["metadata_json"])
            row["deleted_at"] = None
            row["created_at"] = previous["created_at"] if previous is not None else params["created_at"]
            self.db.embeddings[embedding_id] = row
            self.rowcount = 1
            return
        if normalized.startswith("SELECT m.data_json, e.embedding_id"):
            query_embedding = _parse_vector_literal(params["embedding"])
            rows = []
            for embedding_row in self.db.embeddings.values():
                memory_row = self.db.memories.get(str(embedding_row["memory_id"]))
                if memory_row is None:
                    continue
                if embedding_row["deleted_at"] is not None:
                    continue
                if embedding_row["namespace"] != params["namespace"]:
                    continue
                if embedding_row["status"] != params["status"]:
                    continue
                if embedding_row["dimensions"] != params["dimensions"]:
                    continue
                if params.get("provider_id") is not None and embedding_row["provider_id"] != params["provider_id"]:
                    continue
                if params.get("model_id") is not None and embedding_row["model_id"] != params["model_id"]:
                    continue
                if memory_row["status"] != MemoryStatus.ACTIVE.value or memory_row["deleted_at"] is not None:
                    continue
                rows.append(
                    {
                        "data_json": memory_row["data_json"],
                        "embedding_id": embedding_row["embedding_id"],
                        "memory_id": embedding_row["memory_id"],
                        "namespace": embedding_row["namespace"],
                        "provider_id": embedding_row["provider_id"],
                        "model_id": embedding_row["model_id"],
                        "dimensions": embedding_row["dimensions"],
                        "status": embedding_row["status"],
                        "content_hash": embedding_row["content_hash"],
                        "metadata_json": embedding_row["metadata_json"],
                        "created_at": embedding_row["created_at"],
                        "updated_at": embedding_row["updated_at"],
                        "score": _cosine_similarity(embedding_row["embedding"], query_embedding),
                    }
                )
            rows.sort(key=lambda row: (row["score"], row["updated_at"], row["memory_id"]), reverse=True)
            self._fetchall = rows[: int(params["limit"])]
            return
        if normalized.startswith("SELECT status FROM focus_memory_embeddings WHERE memory_id = %s"):
            row = _latest_embedding_row(self.db, memory_id=str(params[0]))
            self._fetchone = {"status": row["status"]} if row and row["deleted_at"] is None else None
            return
        if normalized.startswith("UPDATE focus_memory_embeddings SET status = 'stale'"):
            for row in self.db.embeddings.values():
                if row["memory_id"] != params["memory_id"]:
                    continue
                if row["provider_id"] != params["provider_id"]:
                    continue
                if row["model_id"] != params["model_id"]:
                    continue
                if row["content_hash"] == params["content_hash"]:
                    continue
                if row["status"] != "active" or row["deleted_at"] is not None:
                    continue
                row["status"] = "stale"
                row["deleted_at"] = params["updated_at"]
                row["updated_at"] = params["updated_at"]
                row["metadata_json"] = {
                    **row["metadata_json"],
                    **_json_payload(params["stale_metadata_json"]),
                }
                self.rowcount += 1
            return
        if normalized.startswith("UPDATE focus_memory_embeddings"):
            for row in _active_embedding_rows(self.db, memory_id=str(params["memory_id"])):
                row["status"] = params["status"]
                row["updated_at"] = params["updated_at"]
                if "metadata_json" in params:
                    row["metadata_json"] = {
                        **row["metadata_json"],
                        **_json_payload(params["metadata_json"]),
                    }
                self.rowcount += 1
            return
        if (
            normalized.startswith("SELECT embedding_id, memory_id, namespace, provider_id, model_id")
            and "WHERE memory_id = %s" in normalized
        ):
            row = _latest_embedding_row(self.db, memory_id=str(params[0]))
            self._fetchone = (
                {
                    "embedding_id": row["embedding_id"],
                    "memory_id": row["memory_id"],
                    "namespace": row["namespace"],
                    "provider_id": row["provider_id"],
                    "model_id": row["model_id"],
                    "dimensions": row["dimensions"],
                    "status": row["status"],
                    "content_hash": row["content_hash"],
                    "metadata_json": row["metadata_json"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
                if row and row["deleted_at"] is None
                else None
            )
            return
        if normalized.startswith("SELECT embedding_id, memory_id, namespace, provider_id, model_id"):
            rows = [row for row in self.db.embeddings.values() if row["deleted_at"] is None]
            if params.get("namespace") is not None:
                rows = [row for row in rows if row["namespace"] == params["namespace"]]
            if params.get("provider_id") is not None:
                rows = [row for row in rows if row["provider_id"] == params["provider_id"]]
            if params.get("model_id") is not None:
                rows = [row for row in rows if row["model_id"] == params["model_id"]]
            if params.get("status") is not None:
                rows = [row for row in rows if row["status"] == params["status"]]
            rows.sort(key=lambda row: (row["updated_at"], row["memory_id"]), reverse=True)
            offset = int(params["offset"])
            limit = int(params["limit"])
            self._fetchall = [
                {
                    "embedding_id": row["embedding_id"],
                    "memory_id": row["memory_id"],
                    "namespace": row["namespace"],
                    "provider_id": row["provider_id"],
                    "model_id": row["model_id"],
                    "dimensions": row["dimensions"],
                    "status": row["status"],
                    "content_hash": row["content_hash"],
                    "metadata_json": row["metadata_json"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
                for row in rows[offset : offset + limit]
            ]
            return
        if normalized.startswith("DELETE FROM focus_memory_embeddings WHERE memory_id = %s"):
            memory_id = str(params[0])
            embedding_ids = [
                embedding_id
                for embedding_id, row in self.db.embeddings.items()
                if row["memory_id"] == memory_id
            ]
            for embedding_id in embedding_ids:
                del self.db.embeddings[embedding_id]
            self.rowcount = len(embedding_ids)
            return
        if normalized.startswith("INSERT INTO focus_memory_tombstones"):
            memory_id = str(params["memory_id"])
            tombstone_id = (
                self.db.tombstones[memory_id]["tombstone_id"]
                if memory_id in self.db.tombstones
                else str(params["tombstone_id"])
            )
            row = dict(params)
            row["tombstone_id"] = tombstone_id
            row["data_json"] = _json_payload(params["data_json"])
            self.db.tombstones[memory_id] = row
            self._fetchone = {"tombstone_id": tombstone_id}
            return
        if normalized.startswith("INSERT INTO focus_memory_audit_events"):
            row = dict(params)
            row["data_json"] = _json_payload(params["data_json"])
            self.db.audit_events[str(params["event_id"])] = row
            return
        if normalized.startswith("SELECT data_json FROM focus_memory_audit_events"):
            rows = list(self.db.audit_events.values())
            if params.get("memory_id"):
                rows = [row for row in rows if row["memory_id"] == params["memory_id"]]
            if params.get("user_id"):
                rows = [row for row in rows if row["user_id"] == params["user_id"]]
            if params.get("root_thread_id"):
                rows = [
                    row for row in rows if row["root_thread_id"] == params["root_thread_id"]
                ]
            if params.get("source_thread_id"):
                rows = [
                    row
                    for row in rows
                    if row["source_thread_id"] == params["source_thread_id"]
                ]
            if params.get("source_branch_id"):
                rows = [
                    row
                    for row in rows
                    if row["source_branch_id"] == params["source_branch_id"]
                ]
            rows.sort(key=lambda row: (row["created_at"], row["event_id"]), reverse=True)
            self._fetchall = [
                {"data_json": row["data_json"]}
                for row in rows[: int(params["limit"])]
            ]
            return
        if normalized.startswith("INSERT INTO focus_memory_candidates"):
            row = dict(params)
            row["data_json"] = _json_payload(params["data_json"])
            self.db.candidates[str(params["candidate_id"])] = row
            return
        if normalized.startswith(
            "SELECT data_json FROM focus_memory_candidates WHERE candidate_id = %s"
        ):
            row = self.db.candidates.get(str(params[0]))
            self._fetchone = {"data_json": row["data_json"]} if row else None
            return
        if normalized.startswith("SELECT data_json FROM focus_memory_candidates"):
            rows = list(self.db.candidates.values())
            if params.get("status"):
                rows = [row for row in rows if row["status"] == params["status"]]
            if params.get("root_thread_id"):
                rows = [row for row in rows if row["root_thread_id"] == params["root_thread_id"]]
            if params.get("user_id"):
                rows = [row for row in rows if row["user_id"] == params["user_id"]]
            if params.get("branch_id"):
                rows = [row for row in rows if row["branch_id"] == params["branch_id"]]
            rows.sort(key=lambda row: (row["updated_at"], row["candidate_id"]), reverse=True)
            self._fetchall = [
                {"data_json": row["data_json"]}
                for row in rows[: int(params["limit"])]
            ]
            return
        raise AssertionError(f"unexpected SQL: {normalized}")

    def fetchone(self):
        return self._fetchone

    def fetchall(self):
        return self._fetchall


class _FakeConnection:
    def __init__(self, db: _FakePostgresMemoryDB) -> None:
        self.db = db

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self.db)


def _active_embedding_rows(
    db: _FakePostgresMemoryDB,
    *,
    memory_id: str,
) -> list[dict[str, Any]]:
    return [
        row
        for row in db.embeddings.values()
        if row["memory_id"] == memory_id and row["deleted_at"] is None
    ]


def _latest_embedding_row(
    db: _FakePostgresMemoryDB,
    *,
    memory_id: str,
) -> dict[str, Any] | None:
    rows = _active_embedding_rows(db, memory_id=memory_id)
    rows.sort(key=lambda row: (row["updated_at"], row["embedding_id"]), reverse=True)
    return rows[0] if rows else None


def test_postgres_memory_repository_upsert_search_forget_and_audit(monkeypatch):
    db = _FakePostgresMemoryDB()
    monkeypatch.setattr(
        "focus_agent.repositories.postgres_memory_repository.psycopg.connect",
        lambda uri, row_factory=None: _FakeConnection(db),
    )
    repo = PostgresMemoryRepository("postgresql://example")
    record = _memory_record(
        memory_id="mem-1",
        namespace=("conversation", "root-1", "main"),
        summary="owner collision fix",
        content="The owner collision fix belongs in the repository layer.",
        fingerprint="fp-1",
        semantic_key="sk-1",
    )

    assert repo.upsert_record(record) == "mem-1"
    assert repo.get_record("mem-1") == record
    assert repo.find_existing(
        namespace=record.namespace,
        fingerprint="fp-1",
        semantic_key="missing",
        kind=MemoryKind.PROJECT_FACT.value,
        scope=MemoryScope.ROOT_THREAD.value,
    ) == record
    assert repo.list_records(MemoryListQuery(namespace=record.namespace, status="active")) == [record]

    hits = repo.search(namespace=record.namespace, query="owner collision", limit=5)
    assert [hit.record.memory_id for hit in hits] == ["mem-1"]
    assert hits[0].namespace == record.namespace

    assert repo.upsert_embedding(
        memory_id="mem-1",
        namespace=record.namespace,
        embedding=[0.1, 0.2, 0.3],
        model="test-embedding",
        content_hash="hash-1",
        metadata={"source": "unit-test"},
    ) == "mem-1"
    assert repo.get_embedding_status("mem-1") == "active"
    embedding_hits = repo.search_embeddings(
        namespace=record.namespace,
        embedding=[0.1, 0.2, 0.31],
        model="test-embedding",
        limit=5,
    )
    assert [hit.memory_id for hit in embedding_hits] == ["mem-1"]
    assert embedding_hits[0].record == record
    assert embedding_hits[0].metadata == {"source": "unit-test"}
    assert repo.update_embedding_status(
        memory_id="mem-1",
        status="stale",
        metadata={"reason": "content_changed"},
    )
    assert repo.get_embedding_status("mem-1") == "stale"
    metadata_rows = repo.list_embedding_metadata(
        MemoryEmbeddingListQuery(namespace=record.namespace, status="stale")
    )
    assert len(metadata_rows) == 1
    assert metadata_rows[0].memory_id == "mem-1"
    assert metadata_rows[0].dimensions == 3
    assert metadata_rows[0].metadata == {
        "source": "unit-test",
        "reason": "content_changed",
    }
    assert repo.get_memory_embedding("mem-1") == metadata_rows[0]
    assert repo.search_embeddings(
        namespace=record.namespace,
        embedding=[0.1, 0.2, 0.31],
        model="test-embedding",
        limit=5,
    ) == []
    assert repo.search_embeddings(
        namespace=record.namespace,
        embedding=[0.1, 0.2, 0.31],
        model="test-embedding",
        status="stale",
        limit=5,
    )[0].memory_id == "mem-1"

    audit = MemoryAuditEvent(
        event_id="audit-1",
        action="written",
        decision=MemoryWriteDecisionStatus.ACCEPTED,
        memory_id="mem-1",
        actor="test",
        namespace=record.namespace,
        data={"summary": "owner collision fix"},
    )
    assert repo.append_audit_event(audit) == "audit-1"
    assert repo.list_audit_events(memory_id="mem-1") == [audit]

    tombstone_id = repo.forget_record(
        memory_id="mem-1",
        namespace=record.namespace,
        actor="tester",
        reason="cleanup",
    )

    assert tombstone_id
    assert db.tombstones["mem-1"]["actor"] == "tester"
    tombstone_payload = db.tombstones["mem-1"]["data_json"]
    assert "content" not in tombstone_payload
    assert "summary" not in tombstone_payload
    assert repo.forget_record(memory_id="mem-1", namespace=record.namespace) == tombstone_id
    forgotten = repo.get_record("mem-1")
    assert forgotten is not None
    assert forgotten.status == MemoryStatus.FORGOTTEN
    assert forgotten.deleted_at is not None
    assert forgotten.content == ""
    assert forgotten.summary == "[forgotten]"
    memory_row = db.memories["mem-1"]
    assert memory_row["content"] == ""
    assert memory_row["summary"] == "[forgotten]"
    assert memory_row["status"] == MemoryStatus.FORGOTTEN.value
    assert memory_row["deleted_at"] is not None
    assert memory_row["data_json"]["content"] == ""
    assert memory_row["data_json"]["summary"] == "[forgotten]"
    assert memory_row["data_json"]["status"] == MemoryStatus.FORGOTTEN.value
    assert memory_row["data_json"]["deleted_at"] is not None
    assert db.embeddings == {}
    assert repo.list_records(MemoryListQuery(namespace=record.namespace, status="forgotten")) == [forgotten]
    assert repo.search(namespace=record.namespace, query="owner collision", limit=5) == []


def test_postgres_memory_repository_rebuild_embedding_index_preserves_memories(monkeypatch):
    db = _FakePostgresMemoryDB()
    monkeypatch.setattr(
        "focus_agent.repositories.postgres_memory_repository.psycopg.connect",
        lambda uri, row_factory=None: _FakeConnection(db),
    )

    def fake_rebuild(conn, **kwargs):  # noqa: ARG001
        db.embeddings.clear()

    repo = PostgresMemoryRepository("postgresql://example")
    monkeypatch.setattr(
        "focus_agent.repositories.postgres_memory_repository.rebuild_memory_embedding_index_on_connection",
        fake_rebuild,
    )
    monkeypatch.setattr(
        repo,
        "inspect_pgvector_support",
        lambda **kwargs: {
            "extension_installed": True,
            "embeddings_table_exists": True,
            "dimensions_match": True,
            "configured_dimensions": kwargs["dimensions"],
        },
    )
    record = _memory_record(
        memory_id="mem-rebuild",
        namespace=("conversation", "root-1", "main"),
        summary="keep canonical",
        content="Canonical memory survives embedding index rebuild.",
        fingerprint="fp-rebuild",
        semantic_key="sk-rebuild",
    )

    repo.upsert_record(record)
    repo.upsert_embedding(
        memory_id=record.memory_id,
        namespace=record.namespace,
        embedding=[0.1, 0.2, 0.3],
        provider_id="ollama",
        model_id="embeddinggemma",
        content_hash="hash-rebuild",
    )

    status = repo.rebuild_embedding_index(dimensions=768, vector_index=True)

    assert status["dimensions_match"] is True
    assert db.memories[record.memory_id]["data_json"]["summary"] == "keep canonical"
    assert db.embeddings == {}
    assert repo.dimensions == 768
    assert repo.vector_index is True
    assert repo.memory_embeddings_enabled is True


def test_postgres_memory_repository_stales_old_embedding_when_content_hash_changes(monkeypatch):
    db = _FakePostgresMemoryDB()
    monkeypatch.setattr(
        "focus_agent.repositories.postgres_memory_repository.psycopg.connect",
        lambda uri, row_factory=None: _FakeConnection(db),
    )
    repo = PostgresMemoryRepository("postgresql://example")
    record = _memory_record(
        memory_id="mem-content-change",
        namespace=("conversation", "root-1", "main"),
        summary="content change",
        content="Original content.",
        fingerprint="fp-content-change",
        semantic_key="sk-content-change",
    )
    repo.upsert_record(record)
    repo.upsert_embedding(
        memory_id=record.memory_id,
        namespace=record.namespace,
        embedding=[1.0, 0.0, 0.0],
        provider_id="ollama",
        model_id="embeddinggemma",
        content_hash="hash-old",
    )

    repo.upsert_embedding(
        memory_id=record.memory_id,
        namespace=record.namespace,
        embedding=[0.0, 1.0, 0.0],
        provider_id="ollama",
        model_id="embeddinggemma",
        content_hash="hash-new",
    )

    active_rows = repo.list_embedding_metadata(
        MemoryEmbeddingListQuery(
            namespace=record.namespace,
            provider_id="ollama",
            model_id="embeddinggemma",
            status="active",
        )
    )
    assert [row.content_hash for row in active_rows] == ["hash-new"]
    assert any(
        row["content_hash"] == "hash-old"
        and row["status"] == "stale"
        and row["deleted_at"] is not None
        for row in db.embeddings.values()
    )
    hits = repo.search_embeddings(
        namespace=record.namespace,
        embedding=[1.0, 0.0, 0.0],
        provider_id="ollama",
        model_id="embeddinggemma",
        limit=5,
    )
    assert [hit.content_hash for hit in hits] == ["hash-new"]


def test_postgres_memory_repository_candidates_round_trip(monkeypatch):
    db = _FakePostgresMemoryDB()
    monkeypatch.setattr(
        "focus_agent.repositories.postgres_memory_repository.psycopg.connect",
        lambda uri, row_factory=None: _FakeConnection(db),
    )
    repo = PostgresMemoryRepository("postgresql://example")
    candidate = MemoryCandidate(
        candidate_id="candidate-1",
        status="pending",
        agent_id="agent-1",
        task_id="task-1",
        branch_id="branch-1",
        root_thread_id="root-1",
        user_id="user-1",
        evidence_refs=["trace:1"],
        record=MemoryWriteRequest(
            kind=MemoryKind.BRANCH_FINDING,
            scope=MemoryScope.BRANCH,
            visibility=MemoryVisibility.PROMOTABLE,
            namespace=("conversation", "root-1", "branch", "branch-1", "local_memory"),
            content="Branch-local finding needs review.",
            summary="Branch-local finding",
            root_thread_id="root-1",
            source_branch_id="branch-1",
            user_id="user-1",
        ),
    )

    assert repo.upsert_candidate(candidate) == "candidate-1"
    assert repo.list_candidates(status="pending", root_thread_id="root-1") == [candidate]

    repo.update_candidate_status(
        candidate_id="candidate-1",
        status="accepted",
        reason="approved_for_main_memory",
    )

    accepted = repo.list_candidates(status="accepted", root_thread_id="root-1")
    assert len(accepted) == 1
    assert accepted[0].candidate_id == "candidate-1"
    assert accepted[0].reason == "approved_for_main_memory"


def test_postgres_memory_repository_embedding_payload_aliases(monkeypatch):
    db = _FakePostgresMemoryDB()
    monkeypatch.setattr(
        "focus_agent.repositories.postgres_memory_repository.psycopg.connect",
        lambda uri, row_factory=None: _FakeConnection(db),
    )
    repo = PostgresMemoryRepository("postgresql://example")

    assert repo.upsert_memory_embedding(
        {
            "memory_id": "mem-1",
            "namespace": ("conversation", "root-1", "main"),
            "embedding": [0.4, 0.5],
            "provider_id": "deterministic_test",
            "model_id": "deterministic-test",
            "dimensions": 2,
            "content_hash": "hash-1",
            "metadata": {"source": "payload"},
        }
    ) == "mem-1"

    metadata = repo.get_memory_embedding("mem-1")
    assert metadata is not None
    assert metadata.model_id == "deterministic-test"
    assert metadata.dimensions == 2
    assert metadata.status == "active"
    assert metadata.metadata == {"source": "payload"}
    assert repo.delete_memory_embedding("mem-1")
    assert repo.get_memory_embedding("mem-1") is None


def test_postgres_memory_forgotten_payload_sanitize_migration_is_idempotent():
    executed: list[str] = []
    migration = dict(_MIGRATIONS)[9]

    migration(lambda sql, params=None: executed.append(sql))

    assert SCHEMA_VERSION == 11
    assert len(executed) == 1
    sql = " ".join(executed[0].split())
    assert sql.startswith("UPDATE focus_memories SET")
    assert "content = ''" in sql
    assert "summary = '[forgotten]'" in sql
    assert "data_json" in sql
    assert "WHERE status = 'forgotten'" in sql
    assert "data_json->>'content' IS DISTINCT FROM ''" in sql
    assert "data_json->>'summary' IS DISTINCT FROM '[forgotten]'" in sql
    assert "OR deleted_at IS NULL" in sql


def test_postgres_memory_embeddings_migration_uses_optional_pgvector_storage():
    executed: list[str] = []
    migration = dict(_MIGRATIONS)[10]

    migration(lambda sql, params=None: executed.append(sql))

    assert len(executed) == 6
    combined = " ".join(" ".join(sql.split()) for sql in executed)
    assert "CREATE EXTENSION IF NOT EXISTS vector" in combined
    assert "CREATE TABLE IF NOT EXISTS focus_memory_embeddings" in combined
    assert "embedding vector(1536) NOT NULL" in combined
    assert "idx_focus_memory_embeddings_vector" not in combined
    assert "idx_focus_memory_embeddings_namespace_status_updated" in combined


def test_postgres_memory_embeddings_migration_can_require_preinstalled_pgvector():
    executed: list[str] = []

    _run_migration_v10(
        lambda sql, params=None: executed.append(sql),
        dimensions=64,
        pgvector_extension_mode="required",
    )

    combined = " ".join(" ".join(sql.split()) for sql in executed)
    assert "CREATE EXTENSION IF NOT EXISTS vector" not in combined
    assert "pgvector extension is required" in combined
    assert "SELECT 1 FROM pg_extension WHERE extname = 'vector'" in combined
    assert "embedding vector(64) NOT NULL" in combined


def test_postgres_memory_embeddings_migration_can_create_vector_index():
    executed: list[str] = []

    _run_migration_v10(
        lambda sql, params=None: executed.append(sql),
        vector_index=True,
    )

    combined = " ".join(" ".join(sql.split()) for sql in executed)
    assert "idx_focus_memory_embeddings_vector" in combined
    assert "USING hnsw (embedding vector_cosine_ops)" in combined


def test_rebuild_memory_embedding_index_only_drops_embedding_storage():
    executed: list[str] = []

    class _RecordingCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def execute(self, sql: str, params=None) -> None:  # noqa: ARG002
            executed.append(sql)

        def fetchone(self):
            return None

    class _RecordingConnection:
        def cursor(self):
            return _RecordingCursor()

    rebuild_memory_embedding_index_on_connection(
        _RecordingConnection(),
        dimensions=768,
        vector_index=True,
        pgvector_extension_mode="required",
    )

    combined = " ".join(" ".join(sql.split()) for sql in executed)
    assert "DROP TABLE IF EXISTS focus_memory_embeddings CASCADE" in combined
    assert "CREATE TABLE IF NOT EXISTS focus_memory_embeddings" in combined
    assert "embedding vector(768) NOT NULL" in combined
    assert "idx_focus_memory_embeddings_vector" in combined
    assert "DROP TABLE IF EXISTS focus_memories" not in combined
    assert "DELETE FROM focus_memories" not in combined


def _memory_record(
    *,
    memory_id: str,
    namespace: tuple[str, ...],
    summary: str,
    content: str,
    fingerprint: str,
    semantic_key: str,
) -> MemoryRecord:
    now = datetime(2026, 5, 6, tzinfo=timezone.utc)
    return MemoryRecord(
        memory_id=memory_id,
        kind=MemoryKind.PROJECT_FACT,
        scope=MemoryScope.ROOT_THREAD,
        visibility=MemoryVisibility.SHARED,
        status=MemoryStatus.ACTIVE,
        namespace=namespace,
        content=content,
        summary=summary,
        root_thread_id="root-1",
        user_id="user-1",
        confidence=0.8,
        importance=0.7,
        fingerprint=fingerprint,
        semantic_key=semantic_key,
        created_at=now,
        updated_at=now,
    )


def _json_payload(value: object) -> Any:
    return getattr(value, "obj", value)


def _parse_vector_literal(value: object) -> list[float]:
    if isinstance(value, str):
        stripped = value.strip().removeprefix("[").removesuffix("]")
        if not stripped:
            return []
        return [float(part) for part in stripped.split(",")]
    return [float(part) for part in value]


def _matches_query(row: dict[str, Any], query: str) -> bool:
    if not query:
        return True
    haystack = f"{row['summary']} {row['content']}".casefold()
    return query in haystack or all(term in haystack for term in query.split())


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    dot = sum(left_value * right_value for left_value, right_value in zip(left, right, strict=True))
    left_norm = sum(value * value for value in left) ** 0.5
    right_norm = sum(value * value for value in right) ** 0.5
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def _memory_row_matches_list_query(row: dict[str, Any], params: dict[str, Any]) -> bool:
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
        if field in params and row[field] != params[field]:
            return False
    return "namespace" not in params or row["namespace"] == params["namespace"]
