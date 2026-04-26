from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from focus_agent.api.main import create_app
from focus_agent.config import Settings
from focus_agent.core.branching import BranchRecord, BranchRole, BranchStatus
from focus_agent.security.tokens import create_access_token


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
