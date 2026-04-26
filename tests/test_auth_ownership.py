from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from focus_agent.api.main import create_app
from focus_agent.config import Settings
from focus_agent.core.branching import BranchRecord, BranchRole, BranchStatus
from focus_agent.repositories.sqlite_branch_repository import SQLiteBranchRepository
from focus_agent.security.ownership import (
    OwnershipAuditEvent,
    OwnershipAuditExportSink,
    allow_ownership,
    assert_owner,
    build_ownership_audit_report,
    deny_ownership,
    export_ownership_audit_dashboard,
    export_ownership_audit_events,
)
from focus_agent.security.tokens import Principal, create_access_token


def _with_stub_frontend(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "test-api-key")
    monkeypatch.setenv("WEB_APP_DIST_DIR", str(dist_dir))
    monkeypatch.setenv("WEB_APP_DEV_SERVER_URL", "")
    monkeypatch.setenv("AUTH_ENABLED", "true")


class _OwnershipRepo:
    def __init__(self) -> None:
        self.record = BranchRecord(
            branch_id="branch-1",
            root_thread_id="root-1",
            parent_thread_id="root-1",
            child_thread_id="child-1",
            return_thread_id="root-1",
            owner_user_id="owner-1",
            branch_name="Owner Branch",
            branch_role=BranchRole.DEEP_DIVE,
            branch_depth=1,
            branch_status=BranchStatus.ACTIVE,
            merge_proposal={"summary": "ready", "key_findings": [], "evidence_refs": []},
        )

    def get_by_child_thread_id(self, child_thread_id: str) -> BranchRecord:
        if child_thread_id != self.record.child_thread_id:
            raise KeyError(child_thread_id)
        return self.record


class _OwnershipChatService:
    def _assert_owner(self, user_id: str) -> None:
        if user_id != "owner-1":
            raise PermissionError(f"User {user_id} cannot access thread root-1.")

    def get_thread_state(self, *, thread_id: str, user_id: str, request_id: str | None = None):
        del request_id
        self._assert_owner(user_id)
        return _thread_payload(thread_id)

    def preview_thread_context(self, *, thread_id: str, user_id: str, draft_message: str | None = None):
        del thread_id, draft_message
        self._assert_owner(user_id)
        return {"context_usage": _context_usage()}

    def compact_thread_context(self, *, thread_id: str, user_id: str, trigger: str = "manual"):
        del trigger
        self._assert_owner(user_id)
        return _thread_payload(thread_id)


class _OwnershipBranchService:
    def _assert_owner(self, user_id: str) -> None:
        if user_id != "owner-1":
            raise PermissionError(f"User {user_id} cannot access thread root-1.")

    def fork_branch(self, *, parent_thread_id: str, user_id: str, **kwargs):
        del kwargs
        self._assert_owner(user_id)
        return {
            "branch_id": "branch-2",
            "root_thread_id": "root-1",
            "parent_thread_id": parent_thread_id,
            "child_thread_id": "child-2",
            "return_thread_id": parent_thread_id,
            "owner_user_id": user_id,
            "branch_name": "New Branch",
            "branch_role": "deep_dive",
            "branch_depth": 1,
            "branch_status": "active",
            "is_archived": False,
            "archived_at": None,
            "fork_checkpoint_id": None,
            "fork_strategy": "copy_thread",
            "merge_proposal": None,
            "merge_decision": None,
        }

    def get_branch_tree(self, *, root_thread_id: str, user_id: str):
        self._assert_owner(user_id)
        return {
            "thread_id": root_thread_id,
            "root_thread_id": root_thread_id,
            "branch_name": "main",
            "branch_role": "main",
            "branch_status": "active",
            "children": [],
        }

    def list_archived_branches(self, *, root_thread_id: str, user_id: str):
        del root_thread_id
        self._assert_owner(user_id)
        return []

    def prepare_merge_proposal(self, *, child_thread_id: str, user_id: str):
        del child_thread_id
        self._assert_owner(user_id)
        return {"summary": "ready", "key_findings": [], "open_questions": [], "evidence_refs": [], "artifacts": []}

    def apply_merge_decision(self, *, child_thread_id: str, decision, context, proposal_overrides=None):
        del child_thread_id, decision, proposal_overrides
        self._assert_owner(context.user_id)
        return None


def _context_usage() -> dict[str, object]:
    return {
        "used_tokens": 0,
        "token_limit": 0,
        "remaining_tokens": 0,
        "used_ratio": 0.0,
        "status": "ok",
        "prompt_chars": 0,
        "prompt_budget_chars": 0,
        "tokenizer_mode": "chars_fallback",
        "last_compacted_at": None,
    }


def _thread_payload(thread_id: str) -> dict[str, object]:
    return {
        "thread_id": thread_id,
        "root_thread_id": "root-1",
        "assistant_message": None,
        "rolling_summary": "",
        "selected_model": "openai:gpt-4.1-mini",
        "selected_thinking_mode": "",
        "branch_meta": None,
        "merge_proposal": None,
        "merge_decision": None,
        "merge_queue": [],
        "active_skill_ids": [],
        "messages": [],
        "interrupts": [],
        "trace": {},
        "context_usage": _context_usage(),
    }


def _build_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[TestClient, Settings]:
    _with_stub_frontend(monkeypatch, tmp_path)
    settings = Settings(
        auth_enabled=True,
        auth_demo_tokens_enabled=False,
        auth_jwt_secret="ownership-secret",
        auth_jwt_issuer="focus-agent-test",
        auth_jwt_audience="focus-agent-web",
    )
    app = create_app()
    app.state.runtime = SimpleNamespace(
        settings=settings,
        repo=_OwnershipRepo(),
        branch_service=_OwnershipBranchService(),
        graph=object(),
        tool_registry=object(),
        skill_registry=object(),
    )
    app.state.chat_service = _OwnershipChatService()
    return TestClient(app), settings


def _auth_header(
    settings: Settings,
    *,
    user_id: str,
    tenant_id: str | None = None,
    scopes: list[str] | None = None,
) -> dict[str, str]:
    token = create_access_token(
        settings=settings,
        user_id=user_id,
        tenant_id=tenant_id,
        scopes=scopes or [],
    )
    return {"Authorization": f"Bearer {token}"}


def test_ownership_audit_helpers_collect_allow_and_deny_events() -> None:
    events: list[OwnershipAuditEvent] = []
    principal = Principal(user_id="owner-1", tenant_id="tenant-a", scopes=("threads:read",))

    event = allow_ownership(
        events,
        principal=principal,
        resource_type="thread",
        resource_id="root-1",
        action="read",
        reason="owner_match",
        request_id="req-allow",
    )

    assert event == events[0]
    assert event.principal == "owner-1"
    assert event.user_id == "owner-1"
    assert event.resource_type == "thread"
    assert event.resource_id == "root-1"
    assert event.action == "read"
    assert event.decision == "allow"
    assert event.reason == "owner_match"
    assert event.request_id == "req-allow"

    with pytest.raises(PermissionError, match="cannot write thread root-1"):
        deny_ownership(
            events,
            principal=Principal(user_id="intruder-1"),
            resource_type="thread",
            resource_id="root-1",
            action="write",
            reason="owner_mismatch",
            request_id="req-deny",
        )

    assert [item.decision for item in events] == ["allow", "deny"]
    denied = events[-1]
    assert denied.user_id == "intruder-1"
    assert denied.reason == "owner_mismatch"
    assert denied.request_id == "req-deny"


def test_ownership_audit_export_formats_allow_and_deny_events() -> None:
    events = OwnershipAuditExportSink()

    allow_ownership(
        events,
        principal=Principal(user_id="owner-1", tenant_id="tenant-a", scopes=("threads:read",)),
        resource_type="thread",
        resource_id="root-1",
        action="read",
        reason="owner_match",
        request_id="req-allow",
    )
    with pytest.raises(PermissionError):
        deny_ownership(
            events,
            principal=Principal(user_id="intruder-1"),
            resource_type="thread",
            resource_id="root-1",
            action="write",
            reason="owner_mismatch",
            request_id="req-deny",
        )

    exported = events.export()

    assert exported == export_ownership_audit_events(events)
    assert [item["tool"] for item in exported] == ["ownership.audit", "ownership.audit"]
    assert exported[0]["args"] == {
        "resource_type": "thread",
        "resource_id": "root-1",
        "action": "read",
        "request_id": "req-allow",
    }
    assert exported[0]["error"] is None
    assert exported[0]["runtime"]["decision"] == "allow"
    assert exported[0]["runtime"]["user_id"] == "owner-1"
    assert exported[1]["error"] == "owner_mismatch"
    assert exported[1]["runtime"]["decision"] == "deny"
    assert exported[1]["runtime"]["user_id"] == "intruder-1"
    assert exported[1]["runtime"]["request_id"] == "req-deny"


def test_ownership_audit_dashboard_aggregates_deny_reasons_and_trend() -> None:
    events = OwnershipAuditExportSink()

    allow_ownership(
        events,
        principal=Principal(user_id="owner-1"),
        resource_type="thread",
        resource_id="root-1",
        action="read",
        request_id="req-allow",
    )
    for reason, request_id, action in (
        ("owner_mismatch", "req-deny-1", "read"),
        ("branch_owner_mismatch", "req-deny-2", "merge"),
        ("owner_mismatch", "req-deny-3", "write"),
    ):
        with pytest.raises(PermissionError):
            deny_ownership(
                events,
                principal=Principal(user_id="intruder-1"),
                resource_type="thread",
                resource_id="root-1",
                action=action,
                reason=reason,
                request_id=request_id,
            )

    report = build_ownership_audit_report(events)
    exported = export_ownership_audit_dashboard(events)

    assert report == events.report()
    assert exported == events.export_report()
    assert report["total_events"] == 4
    assert report["allow_count"] == 1
    assert report["deny_count"] == 3
    assert report["deny_rate"] == 0.75
    assert report["by_decision"] == {"allow": 1, "deny": 3}
    assert report["deny_reasons"] == {"branch_owner_mismatch": 1, "owner_mismatch": 2}
    assert report["deny_by_action"] == {"merge": 1, "read": 1, "write": 1}
    assert report["deny_by_principal"] == {"intruder-1": 3}
    assert [item["cumulative_denies"] for item in report["deny_trend"]] == [1, 2, 3]
    assert [item["request_id"] for item in report["deny_trend"]] == [
        "req-deny-1",
        "req-deny-2",
        "req-deny-3",
    ]
    assert exported["tool"] == "ownership.audit.report"
    assert exported["runtime"]["deny_count"] == 3


def test_ownership_audit_uses_user_id_not_tenant_or_scopes() -> None:
    events: list[OwnershipAuditEvent] = []

    allowed = assert_owner(
        events,
        principal=Principal(user_id="owner-1", tenant_id="tenant-b", scopes=()),
        owner_user_id="owner-1",
        resource_type="thread",
        resource_id="root-1",
        action="read",
        request_id="req-owner",
    )

    assert allowed.decision == "allow"
    assert allowed.user_id == "owner-1"

    with pytest.raises(PermissionError):
        assert_owner(
            events,
            principal=Principal(
                user_id="intruder-1",
                tenant_id="tenant-a",
                scopes=("admin", "threads:read", "branches:write"),
            ),
            owner_user_id="owner-1",
            resource_type="thread",
            resource_id="root-1",
            action="read",
            request_id="req-intruder",
        )

    denied = events[-1]
    assert denied.decision == "deny"
    assert denied.user_id == "intruder-1"
    assert denied.reason == "owner_mismatch"
    assert denied.request_id == "req-intruder"


def test_ownership_audit_export_does_not_bypass_with_tenant_or_scopes() -> None:
    events = OwnershipAuditExportSink()

    with pytest.raises(PermissionError):
        assert_owner(
            events,
            principal=Principal(
                user_id="intruder-1",
                tenant_id="tenant-a",
                scopes=("admin", "threads:read", "branches:write"),
            ),
            owner_user_id="owner-1",
            resource_type="thread",
            resource_id="root-1",
            action="read",
            request_id="req-intruder",
        )

    exported = events.export()

    assert len(exported) == 1
    assert exported[0]["runtime"]["decision"] == "deny"
    assert exported[0]["runtime"]["user_id"] == "intruder-1"
    assert exported[0]["runtime"]["reason"] == "owner_mismatch"
    assert exported[0]["runtime"]["request_id"] == "req-intruder"
    assert "tenant-a" not in exported[0]["observation"]
    assert "admin" not in exported[0]["observation"]


def test_repository_thread_ownership_checks_emit_audit_events(tmp_path: Path) -> None:
    repo = SQLiteBranchRepository(str(tmp_path / "state.sqlite"))
    events: list[OwnershipAuditEvent] = []

    repo.ensure_thread_owner(
        thread_id="root-1",
        root_thread_id="root-1",
        owner_user_id="owner-1",
        audit_events=events,
        request_id="req-create",
    )
    repo.assert_thread_owner(
        thread_id="root-1",
        owner_user_id="owner-1",
        audit_events=events,
        request_id="req-owner",
    )

    with pytest.raises(PermissionError, match="User intruder-1 cannot access thread root-1."):
        repo.assert_thread_owner(
            thread_id="root-1",
            owner_user_id="intruder-1",
            audit_events=events,
            request_id="req-deny",
        )

    assert [event.decision for event in events] == ["allow", "allow", "deny"]
    assert [event.request_id for event in events] == ["req-create", "req-owner", "req-deny"]
    assert events[0].reason == "thread_owner_registered"
    assert events[1].reason == "owner_match"
    assert events[2].user_id == "intruder-1"
    assert events[2].reason == "owner_mismatch"

    exported = repo.export_ownership_audit_events(events)
    assert [event["runtime"]["decision"] for event in exported] == ["allow", "allow", "deny"]
    assert exported[2]["tool"] == "ownership.audit"
    assert exported[2]["error"] == "owner_mismatch"


def test_principal_user_id_is_ownership_key_tenant_and_scopes_are_claim_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client, settings = _build_client(monkeypatch, tmp_path)

    owner_headers = _auth_header(
        settings,
        user_id="owner-1",
        tenant_id="tenant-a",
        scopes=[],
    )
    other_tenant_headers = _auth_header(
        settings,
        user_id="owner-1",
        tenant_id="tenant-b",
        scopes=["branches:write"],
    )
    broad_scope_intruder_headers = _auth_header(
        settings,
        user_id="intruder-1",
        tenant_id="tenant-a",
        scopes=["admin", "threads:read", "branches:write"],
    )

    me_response = client.get("/v1/auth/me", headers=other_tenant_headers)
    assert me_response.status_code == 200
    assert me_response.json()["user_id"] == "owner-1"
    assert me_response.json()["tenant_id"] == "tenant-b"
    assert me_response.json()["scopes"] == ["branches:write"]

    assert client.get("/v1/threads/root-1", headers=owner_headers).status_code == 200
    assert client.get("/v1/threads/root-1", headers=other_tenant_headers).status_code == 200

    denied_requests = [
        ("GET", "/v1/threads/root-1", None),
        ("POST", "/v1/threads/root-1/context/preview", {"draft_message": "hello"}),
        ("POST", "/v1/threads/root-1/context/compact", {"trigger": "manual"}),
        ("POST", "/v1/branches/fork", {"parent_thread_id": "root-1"}),
        ("GET", "/v1/branches/tree/root-1", None),
        ("POST", "/v1/branches/child-1/proposal", {}),
        ("POST", "/v1/branches/child-1/merge", {"approved": True, "mode": "summary_only"}),
    ]

    for method, path, payload in denied_requests:
        response = client.request(
            method,
            path,
            headers=broad_scope_intruder_headers,
            json=payload,
        )
        assert response.status_code == 403, f"{method} {path}: {response.text}"
        body = response.json()
        assert body["code"] == 403
        assert "User intruder-1 cannot access thread root-1." in body["message"]
