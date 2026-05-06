from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from focus_agent.api.routers.memory import router as memory_router
from focus_agent.config import Settings
from focus_agent.memory.models import (
    MemoryAuditEvent,
    MemoryCandidate,
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemorySearchHit,
    MemoryStatus,
    MemoryVisibility,
    MemoryWriteRequest,
)
from focus_agent.repositories.memory_repository import MemoryListQuery
from focus_agent.repositories.user_repository import InMemoryUserRepository
from focus_agent.security.tokens import create_access_token
from focus_agent.services.auth import AuthService
from focus_agent.services.users import UserService


class _MemoryApiRepository:
    def __init__(self) -> None:
        self.records: dict[str, MemoryRecord] = {}
        self.audit_events: list[MemoryAuditEvent] = []
        self.candidates: list[MemoryCandidate] = []
        self.forgotten: list[str] = []

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
        del namespace, fingerprint, semantic_key, kind, scope
        return None

    def search(
        self,
        *,
        namespace: tuple[str, ...],
        query: str,
        limit: int,
    ) -> list[MemorySearchHit]:
        del namespace, query, limit
        return []

    def list_records(self, query: MemoryListQuery) -> list[MemoryRecord]:
        records = list(self.records.values())
        if query.user_id is not None:
            records = [record for record in records if record.user_id == query.user_id]
        if query.root_thread_id is not None:
            records = [record for record in records if record.root_thread_id == query.root_thread_id]
        if query.source_thread_id is not None:
            records = [
                record for record in records if record.source_thread_id == query.source_thread_id
            ]
        if query.source_branch_id is not None:
            records = [
                record for record in records if record.source_branch_id == query.source_branch_id
            ]
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
        if record is None or (namespace is not None and namespace != record.namespace):
            return None
        self.forgotten.append(memory_id)
        self.records[memory_id] = record.model_copy(
            update={
                "status": MemoryStatus.FORGOTTEN,
                "deleted_at": datetime.now(timezone.utc),
            }
        )
        return f"tombstone-{memory_id}"

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
        if memory_id is not None:
            events = [event for event in events if event.memory_id == memory_id]
        if user_id is not None:
            events = [event for event in events if event.user_id == user_id]
        if root_thread_id is not None:
            events = [event for event in events if event.root_thread_id == root_thread_id]
        if source_thread_id is not None:
            events = [event for event in events if event.source_thread_id == source_thread_id]
        if source_branch_id is not None:
            events = [
                event for event in events if event.source_branch_id == source_branch_id
            ]
        return events[:limit]

    def upsert_candidate(self, candidate: MemoryCandidate) -> str:
        self.candidates.append(candidate)
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
        candidates = self.candidates
        if status is not None:
            candidates = [candidate for candidate in candidates if candidate.status == status]
        if root_thread_id is not None:
            candidates = [
                candidate for candidate in candidates if candidate.root_thread_id == root_thread_id
            ]
        if user_id is not None:
            candidates = [candidate for candidate in candidates if candidate.user_id == user_id]
        if branch_id is not None:
            candidates = [
                candidate for candidate in candidates if candidate.branch_id == branch_id
            ]
        return candidates[:limit]

    def update_candidate_status(
        self,
        *,
        candidate_id: str,
        status: str,
        reason: str | None = None,
    ) -> None:
        del candidate_id, status, reason


def _record(memory_id: str, *, user_id: str) -> MemoryRecord:
    return MemoryRecord(
        memory_id=memory_id,
        kind=MemoryKind.USER_PROFILE,
        scope=MemoryScope.USER,
        visibility=MemoryVisibility.SHARED,
        namespace=("memory", "user", user_id, "profile"),
        content=f"profile for {user_id}",
        summary=f"profile for {user_id}",
        user_id=user_id,
    )


def _candidate(candidate_id: str, *, user_id: str) -> MemoryCandidate:
    return MemoryCandidate(
        candidate_id=candidate_id,
        user_id=user_id,
        root_thread_id="root-1",
        record=MemoryWriteRequest(
            kind=MemoryKind.PROJECT_FACT,
            scope=MemoryScope.ROOT_THREAD,
            visibility=MemoryVisibility.PROMOTABLE,
            namespace=("memory", "conversation", "root-1", "branch", "b1"),
            content="candidate",
            summary="candidate",
            user_id=user_id,
            root_thread_id="root-1",
        ),
    )


class _BranchAccessRepository:
    def __init__(
        self,
        *,
        thread_owners: dict[str, str] | None = None,
        branch_owners: dict[str, str] | None = None,
    ) -> None:
        self.thread_owners = thread_owners or {}
        self.branch_owners = branch_owners or {}

    def assert_thread_owner(self, *, thread_id: str, owner_user_id: str) -> None:
        if self.thread_owners.get(thread_id) != owner_user_id:
            raise PermissionError("owner mismatch")

    def get(self, branch_id: str) -> SimpleNamespace:
        owner_user_id = self.branch_owners.get(branch_id)
        if owner_user_id is None:
            raise KeyError(branch_id)
        return SimpleNamespace(branch_id=branch_id, owner_user_id=owner_user_id)


def _client(
    repo: _MemoryApiRepository,
    *,
    users: dict[str, list[str]] | None = None,
    branch_repo: _BranchAccessRepository | None = None,
) -> tuple[TestClient, Settings]:
    settings = Settings(
        auth_enabled=True,
        auth_jwt_secret="memory-api-secret",
        auth_jwt_issuer="focus-agent-memory-api-test",
    )
    user_repo = InMemoryUserRepository()
    user_service = UserService(user_repo, auth_enabled=True)
    for user_id, roles in (users or {}).items():
        user_service.create_user(user_id=user_id, roles=roles)
    app = FastAPI()
    app.include_router(memory_router)
    app.state.runtime = SimpleNamespace(
        settings=settings,
        memory_repository=repo,
        repo=branch_repo,
        user_repository=user_repo,
        user_service=user_service,
        auth_service=AuthService(user_repo, settings=settings),
    )
    return TestClient(app), settings


def _headers(settings: Settings, user_id: str, scopes: list[str] | None = None) -> dict[str, str]:
    token = create_access_token(settings=settings, user_id=user_id, scopes=scopes or [])
    return {"Authorization": f"Bearer {token}"}


def test_memory_api_scopes_record_list_to_current_principal() -> None:
    repo = _MemoryApiRepository()
    repo.records = {
        "mem-owner": _record("mem-owner", user_id="owner-1"),
        "mem-other": _record("mem-other", user_id="other-1"),
    }
    client, settings = _client(repo, users={"owner-1": ["member"], "other-1": ["member"]})

    response = client.get("/v1/memory", headers=_headers(settings, "owner-1"))

    assert response.status_code == 200
    assert [item["memory_id"] for item in response.json()["items"]] == ["mem-owner"]

    denied = client.get(
        "/v1/memory?user_id=other-1",
        headers=_headers(settings, "owner-1"),
    )
    assert denied.status_code == 403


def test_memory_api_hides_detail_and_forget_for_other_users() -> None:
    repo = _MemoryApiRepository()
    repo.records = {
        "mem-owner": _record("mem-owner", user_id="owner-1"),
        "mem-other": _record("mem-other", user_id="other-1"),
    }
    client, settings = _client(repo, users={"owner-1": ["member"], "other-1": ["member"]})

    hidden = client.get("/v1/memory/mem-other", headers=_headers(settings, "owner-1"))
    denied_forget = client.post(
        "/v1/memory/mem-other/forget",
        headers=_headers(settings, "owner-1"),
        json={"reason": "wrong-user"},
    )
    allowed_forget = client.post(
        "/v1/memory/mem-owner/forget",
        headers=_headers(settings, "owner-1"),
        json={"reason": "owner-request"},
    )
    forgotten_detail = client.get("/v1/memory/mem-owner", headers=_headers(settings, "owner-1"))
    forgotten_list = client.get(
        "/v1/memory?status=forgotten",
        headers=_headers(settings, "owner-1"),
    )

    assert hidden.status_code == 404
    assert denied_forget.status_code == 404
    assert allowed_forget.status_code == 200
    assert repo.forgotten == ["mem-owner"]
    assert forgotten_detail.status_code == 200
    assert forgotten_detail.json()["item"]["content"] == ""
    assert forgotten_detail.json()["item"]["summary"] == "[forgotten]"
    assert forgotten_detail.json()["item"]["payload_redacted"] is True
    assert forgotten_list.status_code == 200
    assert forgotten_list.json()["items"][0]["content"] == ""


def test_memory_api_filters_audit_and_candidates_to_current_principal() -> None:
    repo = _MemoryApiRepository()
    repo.records = {
        "mem-owner": _record("mem-owner", user_id="owner-1"),
        "mem-other": _record("mem-other", user_id="other-1"),
    }
    repo.audit_events = [
        MemoryAuditEvent(
            event_id="audit-owner",
            action="memory.upsert",
            decision="accepted",
            memory_id="mem-owner",
            user_id="owner-1",
        ),
        MemoryAuditEvent(
            event_id="audit-other",
            action="memory.upsert",
            decision="accepted",
            memory_id="mem-other",
            user_id="other-1",
        ),
    ]
    repo.candidates = [
        _candidate("candidate-owner", user_id="owner-1"),
        _candidate("candidate-other", user_id="other-1"),
    ]
    client, settings = _client(repo, users={"owner-1": ["member"], "other-1": ["member"]})

    audit = client.get("/v1/memory/audit", headers=_headers(settings, "owner-1"))
    hidden_audit = client.get(
        "/v1/memory/mem-other/audit",
        headers=_headers(settings, "owner-1"),
    )
    candidates = client.get("/v1/memory/candidates", headers=_headers(settings, "owner-1"))

    assert audit.status_code == 200
    assert [item["event_id"] for item in audit.json()["items"]] == ["audit-owner"]
    assert hidden_audit.status_code == 404
    assert candidates.status_code == 200
    assert [item["candidate_id"] for item in candidates.json()["items"]] == ["candidate-owner"]


def test_memory_api_ignores_jwt_audit_scope_for_global_access() -> None:
    repo = _MemoryApiRepository()
    repo.records = {
        "mem-owner": _record("mem-owner", user_id="owner-1"),
        "mem-other": _record("mem-other", user_id="other-1"),
    }
    repo.audit_events = [
        MemoryAuditEvent(
            event_id="audit-owner",
            action="memory.upsert",
            decision="accepted",
            memory_id="mem-owner",
            user_id="owner-1",
        ),
        MemoryAuditEvent(
            event_id="audit-other",
            action="memory.upsert",
            decision="accepted",
            memory_id="mem-other",
            user_id="other-1",
        ),
    ]
    client, settings = _client(repo, users={"owner-1": ["member"], "other-1": ["member"]})

    records = client.get("/v1/memory", headers=_headers(settings, "owner-1", scopes=["audit:read"]))
    audit = client.get(
        "/v1/memory/audit",
        headers=_headers(settings, "owner-1", scopes=["audit:read"]),
    )

    assert records.status_code == 200
    assert [item["memory_id"] for item in records.json()["items"]] == ["mem-owner"]
    assert audit.status_code == 200
    assert [item["event_id"] for item in audit.json()["items"]] == ["audit-owner"]


def test_memory_api_admin_can_global_read_audit_and_candidates() -> None:
    repo = _MemoryApiRepository()
    repo.records = {
        "mem-owner": _record("mem-owner", user_id="owner-1"),
        "mem-other": _record("mem-other", user_id="other-1"),
    }
    repo.audit_events = [
        MemoryAuditEvent(
            event_id="audit-owner",
            action="memory.upsert",
            decision="accepted",
            memory_id="mem-owner",
            user_id="owner-1",
        ),
        MemoryAuditEvent(
            event_id="audit-other",
            action="memory.upsert",
            decision="accepted",
            memory_id="mem-other",
            user_id="other-1",
        ),
    ]
    repo.candidates = [
        _candidate("candidate-owner", user_id="owner-1"),
        _candidate("candidate-other", user_id="other-1"),
    ]
    client, settings = _client(
        repo,
        users={"admin-1": ["admin"], "owner-1": ["member"], "other-1": ["member"]},
    )
    headers = _headers(settings, "admin-1")

    records = client.get("/v1/memory", headers=headers)
    audit = client.get("/v1/memory/audit", headers=headers)
    candidates = client.get("/v1/memory/candidates", headers=headers)

    assert records.status_code == 200
    assert {item["memory_id"] for item in records.json()["items"]} == {"mem-owner", "mem-other"}
    assert audit.status_code == 200
    assert {item["event_id"] for item in audit.json()["items"]} == {"audit-owner", "audit-other"}
    assert candidates.status_code == 200
    assert {item["candidate_id"] for item in candidates.json()["items"]} == {
        "candidate-owner",
        "candidate-other",
    }


def test_memory_api_root_thread_filter_cannot_bypass_ownership() -> None:
    repo = _MemoryApiRepository()
    repo.records = {
        "mem-thread": MemoryRecord(
            memory_id="mem-thread",
            kind=MemoryKind.PROJECT_FACT,
            scope=MemoryScope.ROOT_THREAD,
            visibility=MemoryVisibility.SHARED,
            namespace=("memory", "conversation", "root-1"),
            content="thread memory",
            summary="thread memory",
            user_id="other-1",
            root_thread_id="root-1",
        )
    }
    branch_repo = _BranchAccessRepository(thread_owners={"root-1": "other-1"})
    client, settings = _client(
        repo,
        users={"owner-1": ["member"], "other-1": ["member"]},
        branch_repo=branch_repo,
    )

    response = client.get(
        "/v1/memory?root_thread_id=root-1",
        headers=_headers(settings, "owner-1"),
    )

    assert response.status_code == 403
