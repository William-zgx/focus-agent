from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from focus_agent.core.request_context import RequestContext
from focus_agent.memory.embedding import (
    DeterministicTestEmbeddingProvider,
    MemoryEmbeddingService,
    memory_embedding_text,
)
from focus_agent.memory.models import (
    MemoryAuditEvent,
    MemoryCandidate,
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemorySearchHit,
    MemoryStatus,
    MemoryVisibility,
    MemoryWriteDecisionStatus,
    MemoryWriteRequest,
)
from focus_agent.memory.service import MemoryService
from focus_agent.repositories.memory_repository import MemoryListQuery
from focus_agent.storage.namespaces import project_memory_namespace, user_profile_namespace


class _FakeMemoryRepository:
    def __init__(self) -> None:
        self.records: dict[str, MemoryRecord] = {}
        self.audit_events: list[MemoryAuditEvent] = []
        self.tombstones: dict[str, str] = {}
        self.candidates: dict[str, MemoryCandidate] = {}

    def setup(self) -> None:
        return None

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
        for record in self.records.values():
            if record.namespace != namespace:
                continue
            if record.status == MemoryStatus.FORGOTTEN or record.deleted_at is not None:
                continue
            if kind and record.kind.value != kind:
                continue
            if scope and record.scope.value != scope:
                continue
            if record.fingerprint == fingerprint or record.semantic_key == semantic_key:
                return record
        return None

    def search(
        self,
        *,
        namespace: tuple[str, ...],
        query: str,
        limit: int,
    ) -> list[MemorySearchHit]:
        query_text = query.casefold()
        hits = [
            MemorySearchHit(record=record, score=0.7, namespace=record.namespace)
            for record in self.records.values()
            if record.namespace == namespace
            and record.status == MemoryStatus.ACTIVE
            and query_text in f"{record.summary} {record.content}".casefold()
        ]
        return hits[:limit]

    def list_records(self, query: MemoryListQuery) -> list[MemoryRecord]:
        records = list(self.records.values())
        if query.namespace is not None:
            records = [record for record in records if record.namespace == query.namespace]
        if query.status is not None:
            records = [record for record in records if record.status.value == query.status]
        return records[query.offset : query.offset + query.limit]

    def get_record(self, memory_id: str) -> MemoryRecord | None:
        return self.records.get(memory_id)

    def forget_record(
        self,
        *,
        memory_id: str,
        namespace: tuple[str, ...] | None = None,
        actor: str | None = None,
        reason: str | None = None,
    ) -> str | None:
        del actor, reason
        record = self.records.get(memory_id)
        if record is None or (namespace is not None and record.namespace != namespace):
            return None
        tombstone_id = f"tombstone-{memory_id}"
        self.tombstones[memory_id] = tombstone_id
        self.records[memory_id] = record.model_copy(
            update={
                "status": MemoryStatus.FORGOTTEN,
                "content": "",
                "summary": "[forgotten]",
                "deleted_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }
        )
        return tombstone_id

    def append_audit_event(self, event: MemoryAuditEvent) -> str:
        self.audit_events.append(event)
        return event.event_id

    def list_audit_events(
        self,
        *,
        memory_id: str | None = None,
        user_id: str | None = None,
        root_thread_id: str | None = None,
        source_thread_id: str | None = None,
        source_branch_id: str | None = None,
        limit: int = 50,
    ) -> list[MemoryAuditEvent]:
        events = self.audit_events
        if memory_id:
            events = [event for event in events if event.memory_id == memory_id]
        if user_id:
            events = [event for event in events if event.user_id == user_id]
        if root_thread_id:
            events = [event for event in events if event.root_thread_id == root_thread_id]
        if source_thread_id:
            events = [event for event in events if event.source_thread_id == source_thread_id]
        if source_branch_id:
            events = [event for event in events if event.source_branch_id == source_branch_id]
        return events[:limit]

    def upsert_candidate(self, candidate: MemoryCandidate) -> str:
        self.candidates[candidate.candidate_id] = candidate
        return candidate.candidate_id

    def list_candidates(
        self,
        *,
        status: str | None = None,
        root_thread_id: str | None = None,
        user_id: str | None = None,
        branch_id: str | None = None,
        limit: int = 50,
    ) -> list[MemoryCandidate]:
        candidates = list(self.candidates.values())
        if status is not None:
            candidates = [candidate for candidate in candidates if candidate.status == status]
        if root_thread_id is not None:
            candidates = [
                candidate for candidate in candidates if candidate.root_thread_id == root_thread_id
            ]
        if user_id is not None:
            candidates = [candidate for candidate in candidates if candidate.user_id == user_id]
        if branch_id is not None:
            candidates = [candidate for candidate in candidates if candidate.branch_id == branch_id]
        return candidates[:limit]

    def update_candidate_status(
        self,
        *,
        candidate_id: str,
        status: str,
        reason: str | None = None,
    ) -> None:
        candidate = self.candidates.get(candidate_id)
        if candidate is None:
            return
        self.candidates[candidate_id] = candidate.model_copy(
            update={"status": status, "reason": reason}
        )


class _RejectingPolicy:
    def should_persist(
        self,
        *,
        record: MemoryWriteRequest,
        context: RequestContext,
        state: dict[str, Any],
    ) -> bool:
        del record, context, state
        return False


class _RecordingEmbeddingService:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[MemoryRecord] = []

    def ensure_embedding(self, record: MemoryRecord) -> None:
        self.calls.append(record)
        if self.fail:
            raise RuntimeError("embedding backend unavailable")


class _FakeMemoryEmbeddingRepository:
    def __init__(self) -> None:
        self.embeddings: dict[str, dict[str, Any]] = {}
        self.upsert_calls = 0

    def get_memory_embedding(self, memory_id: str) -> dict[str, Any] | None:
        return self.embeddings.get(memory_id)

    def upsert_memory_embedding(self, **payload: Any) -> str:
        self.upsert_calls += 1
        memory_id = str(payload["memory_id"])
        self.embeddings[memory_id] = dict(payload)
        return memory_id


def test_memory_service_redacts_sensitive_content_in_records_decisions_and_audit():
    repo = _FakeMemoryRepository()
    service = MemoryService(repository=repo)
    request = MemoryWriteRequest(
        kind=MemoryKind.USER_PROFILE,
        scope=MemoryScope.USER,
        visibility=MemoryVisibility.SHARED,
        namespace=user_profile_namespace("user-1"),
        content="Contact jane@example.com and password=supersecret for account recovery.",
        summary="Email jane@example.com, password=supersecret",
        tags=["profile"],
        user_id="user-1",
        importance=0.9,
    )

    decision = service.upsert_request(request, actor="unit-test", reason="save_profile")

    assert decision.status == MemoryWriteDecisionStatus.ACCEPTED
    stored = next(iter(repo.records.values()))
    assert "[redacted]" in stored.content
    assert "jane@example.com" not in stored.content
    assert "supersecret" not in stored.content
    assert "redacted" in stored.tags
    audit_json = json.dumps(repo.audit_events[0].data, ensure_ascii=False)
    assert "jane@example.com" not in audit_json
    assert "supersecret" not in audit_json
    assert "jane@example.com" not in json.dumps(decision.redacted_payload, ensure_ascii=False)


def test_memory_service_merges_same_semantic_key_and_marks_conflicts():
    repo = _FakeMemoryRepository()
    service = MemoryService(repository=repo)
    first = MemoryWriteRequest(
        kind=MemoryKind.USER_PREFERENCE,
        scope=MemoryScope.USER,
        visibility=MemoryVisibility.SHARED,
        namespace=user_profile_namespace("user-1"),
        content="请用中文回答。",
        summary="请用中文回答。",
        user_id="user-1",
        importance=0.8,
        semantic_key="pref-language",
    )
    second = first.model_copy(
        update={
            "content": "请用英文回答。",
            "summary": "请用英文回答。",
            "semantic_key": "pref-language",
        }
    )

    accepted = service.upsert_request(first, actor="unit-test", reason="first")
    merged = service.upsert_request(second, actor="unit-test", reason="replacement")

    assert accepted.status == MemoryWriteDecisionStatus.ACCEPTED
    assert merged.status == MemoryWriteDecisionStatus.MERGED
    assert merged.memory_id == accepted.memory_id
    assert len(repo.records) == 1
    assert next(iter(repo.records.values())).content == "请用英文回答。"

    project_first = MemoryWriteRequest(
        kind=MemoryKind.PROJECT_FACT,
        scope=MemoryScope.PROJECT,
        visibility=MemoryVisibility.SHARED,
        namespace=project_memory_namespace("project-1"),
        content="Default output language is Chinese.",
        summary="Default output language is Chinese.",
        user_id="user-1",
        root_thread_id="root-1",
        importance=0.7,
        semantic_key="project-default",
    )
    project_second = project_first.model_copy(
        update={
            "content": "Release owner is platform operations.",
            "summary": "Release owner is platform operations.",
            "semantic_key": "project-default",
        }
    )

    service.upsert_request(project_first, actor="unit-test", reason="project")
    conflict = service.upsert_request(project_second, actor="unit-test", reason="project")

    assert conflict.status == MemoryWriteDecisionStatus.CONFLICT
    assert conflict.action == "possible_conflict"
    assert repo.records[conflict.memory_id].status == MemoryStatus.CONFLICT
    assert repo.audit_events[-1].action == "possible_conflict"


def test_memory_service_forget_records_tombstone_audit_and_not_found_decision():
    repo = _FakeMemoryRepository()
    service = MemoryService(repository=repo)
    decision = service.upsert_request(
        MemoryWriteRequest(
            kind=MemoryKind.PROJECT_FACT,
            scope=MemoryScope.PROJECT,
            visibility=MemoryVisibility.SHARED,
            namespace=project_memory_namespace("project-1"),
            content="Project uses schema v8 for canonical memory.",
            summary="Project memory schema v8",
            user_id="user-1",
            root_thread_id="root-1",
            source_thread_id="thread-1",
            source_branch_id="branch-1",
            importance=0.7,
        )
    )

    forgotten = service.forget(
        memory_id=decision.memory_id or "",
        actor="unit-test",
        reason="cleanup",
    )
    missing = service.forget(
        memory_id="missing-memory",
        namespace=project_memory_namespace("project-1"),
        actor="unit-test",
    )

    assert forgotten.status == MemoryWriteDecisionStatus.FORGOTTEN
    assert forgotten.tombstone_id == f"tombstone-{decision.memory_id}"
    assert forgotten.audit_id == repo.audit_events[-2].event_id
    assert forgotten.redacted_payload == {"tombstone_id": f"tombstone-{decision.memory_id}"}
    assert repo.audit_events[-2].data == {"tombstone_id": f"tombstone-{decision.memory_id}"}
    assert repo.audit_events[-2].namespace == project_memory_namespace("project-1")
    assert repo.audit_events[-2].user_id == "user-1"
    assert repo.audit_events[-2].root_thread_id == "root-1"
    assert repo.audit_events[-2].source_thread_id == "thread-1"
    assert repo.audit_events[-2].source_branch_id == "branch-1"
    assert repo.records[decision.memory_id].status == MemoryStatus.FORGOTTEN
    assert repo.records[decision.memory_id].content == ""
    assert repo.records[decision.memory_id].summary == "[forgotten]"
    assert missing.status == MemoryWriteDecisionStatus.SKIPPED
    assert missing.reason == "not_found"
    assert repo.audit_events[-1].data == {}


def test_memory_service_persist_records_emits_skip_decision_when_policy_rejects():
    repo = _FakeMemoryRepository()
    service = MemoryService(repository=repo, policy=_RejectingPolicy())
    request = MemoryWriteRequest(
        kind=MemoryKind.USER_PREFERENCE,
        scope=MemoryScope.USER,
        visibility=MemoryVisibility.SHARED,
        namespace=user_profile_namespace("user-1"),
        content="Please keep answers concise.",
        summary="Concise answers",
        user_id="user-1",
        importance=0.8,
    )

    outcome = service.persist_records(
        [request],
        context=RequestContext(user_id="user-1", root_thread_id="root-1"),
        state={},
        actor="memory_pipeline",
    )

    assert outcome["written"] == []
    assert outcome["skipped"] == [{"summary": "Concise answers", "reason": "policy"}]
    assert outcome["decisions"][0]["status"] == MemoryWriteDecisionStatus.SKIPPED.value
    assert repo.records == {}
    assert repo.audit_events[0].action == "policy"


def test_memory_service_writes_embeddings_after_accept_and_merge(monkeypatch):
    monkeypatch.setenv("FOCUS_AGENT_MEMORY_EMBED_ASYNC", "false")
    repo = _FakeMemoryRepository()
    embedding_service = _RecordingEmbeddingService()
    service = MemoryService(repository=repo, embedding_service=embedding_service)
    first = MemoryWriteRequest(
        kind=MemoryKind.USER_PREFERENCE,
        scope=MemoryScope.USER,
        visibility=MemoryVisibility.SHARED,
        namespace=user_profile_namespace("user-1"),
        content="Please keep answers concise.",
        summary="Please keep answers concise.",
        user_id="user-1",
        importance=0.8,
        semantic_key="pref-answer-style",
    )
    second = first.model_copy(
        update={
            "content": "Please keep answers direct.",
            "summary": "Please keep answers direct.",
            "importance": 0.9,
        }
    )

    accepted = service.upsert_request(first, actor="unit-test", reason="first")
    merged = service.upsert_request(second, actor="unit-test", reason="merge")

    assert accepted.status == MemoryWriteDecisionStatus.ACCEPTED
    assert merged.status == MemoryWriteDecisionStatus.MERGED
    assert [record.memory_id for record in embedding_service.calls] == [
        accepted.memory_id,
        merged.memory_id,
    ]
    assert embedding_service.calls[-1].content == "Please keep answers direct."


def test_memory_service_embedding_failure_does_not_block_write(monkeypatch):
    monkeypatch.setenv("FOCUS_AGENT_MEMORY_EMBED_ASYNC", "false")
    repo = _FakeMemoryRepository()
    service = MemoryService(
        repository=repo,
        embedding_service=_RecordingEmbeddingService(fail=True),
    )
    request = MemoryWriteRequest(
        kind=MemoryKind.PROJECT_FACT,
        scope=MemoryScope.PROJECT,
        visibility=MemoryVisibility.SHARED,
        namespace=project_memory_namespace("project-1"),
        content="Project uses canonical memory writes.",
        summary="Canonical memory writes",
        root_thread_id="root-1",
    )

    decision = service.upsert_request(request, actor="unit-test", reason="nonblocking")

    assert decision.status == MemoryWriteDecisionStatus.ACCEPTED
    assert decision.memory_id in repo.records
    assert repo.audit_events[-1].action == "written"


def test_memory_embedding_service_text_hash_and_idempotent_upsert():
    embedding_repo = _FakeMemoryEmbeddingRepository()
    service = MemoryEmbeddingService(
        repository=embedding_repo,
        provider=DeterministicTestEmbeddingProvider(dimensions=4),
    )
    record = MemoryRecord(
        memory_id="memory-1",
        kind=MemoryKind.PROJECT_FACT,
        scope=MemoryScope.PROJECT,
        visibility=MemoryVisibility.SHARED,
        status=MemoryStatus.ACTIVE,
        namespace=project_memory_namespace("project-1"),
        content="Project deploys from the release branch.",
        summary="Deploys from release branch",
        tags=["release", "project"],
    )

    first = service.ensure_embedding(record)
    second = service.ensure_embedding(record)
    updated = service.ensure_embedding(
        record.model_copy(update={"content": "Project deploys from the main branch."})
    )

    assert first["status"] == "written"
    assert second["status"] == "skipped"
    assert second["reason"] == "content_hash_match"
    assert updated["status"] == "written"
    assert embedding_repo.upsert_calls == 2
    assert first["content_hash"] != updated["content_hash"]
    assert embedding_repo.embeddings["memory-1"]["content_hash"] == updated["content_hash"]
    assert "Deploys from release branch" in memory_embedding_text(record)
