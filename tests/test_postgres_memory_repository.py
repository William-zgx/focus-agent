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
from focus_agent.repositories.memory_repository import MemoryListQuery
from focus_agent.repositories.postgres_memory_repository import PostgresMemoryRepository
from focus_agent.repositories.postgres_schema import SCHEMA_VERSION, _MIGRATIONS


class _FakePostgresMemoryDB:
    def __init__(self) -> None:
        self.memories: dict[str, dict[str, Any]] = {}
        self.audit_events: dict[str, dict[str, Any]] = {}
        self.tombstones: dict[str, dict[str, Any]] = {}
        self.candidates: dict[str, dict[str, Any]] = {}


class _FakeCursor:
    def __init__(self, db: _FakePostgresMemoryDB) -> None:
        self.db = db
        self._fetchone: dict[str, Any] | None = None
        self._fetchall: list[dict[str, Any]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute(self, sql: str, params=None) -> None:  # noqa: C901, PLR0912
        normalized = " ".join(sql.split())
        self._fetchone = None
        self._fetchall = []
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
    assert repo.list_records(MemoryListQuery(namespace=record.namespace, status="forgotten")) == [forgotten]
    assert repo.search(namespace=record.namespace, query="owner collision", limit=5) == []


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


def test_postgres_memory_forgotten_payload_sanitize_migration_is_idempotent():
    executed: list[str] = []
    migration = dict(_MIGRATIONS)[9]

    migration(lambda sql, params=None: executed.append(sql))

    assert SCHEMA_VERSION == 9
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


def _matches_query(row: dict[str, Any], query: str) -> bool:
    if not query:
        return True
    haystack = f"{row['summary']} {row['content']}".casefold()
    return query in haystack or all(term in haystack for term in query.split())


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
