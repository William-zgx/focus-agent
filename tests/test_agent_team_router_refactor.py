from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from focus_agent.api.deps import get_app_runtime, get_current_principal
from focus_agent.api.routers import agent_team
from focus_agent.security.tokens import Principal


class FakeApprovalQueue:
    def __init__(self) -> None:
        self.requests = {
            "approval-1": SimpleNamespace(
                request_id="approval-1",
                session_id="session-1",
                agent_id="agent-1",
                tool_name="workspace.write",
                tool_args={"path": "src/example.py"},
                risk_level="high",
                status="pending",
                submitted_at=10.0,
                timeout_at=20.0,
                decided_by=None,
            )
        }

    def get(self, request_id: str) -> object | None:
        return self.requests.get(request_id)

    def list_pending(self) -> list[object]:
        return [request for request in self.requests.values() if request.status == "pending"]

    def decide(self, *, request_id: str, approved: bool, decided_by: str) -> None:
        request = self.requests[request_id]
        request.status = "approved" if approved else "rejected"
        request.decided_by = decided_by


class FakeAgentTeamService:
    def __init__(self) -> None:
        self.coordination_backend = SimpleNamespace(approval_queue=FakeApprovalQueue())

    def get_session(self, session_id: str, *, user_id: str) -> object:
        if session_id != "session-1":
            raise KeyError(session_id)
        return SimpleNamespace(session_id=session_id, root_thread_id="root-thread-1")


def _client(service: FakeAgentTeamService) -> TestClient:
    app = FastAPI()
    app.include_router(agent_team.router)
    app.dependency_overrides[get_app_runtime] = lambda: SimpleNamespace(agent_team_service=service)
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id="user-1")
    return TestClient(app)


def test_tool_approval_routes_preserve_response_and_openapi_contracts() -> None:
    client = _client(FakeAgentTeamService())

    listed = client.get("/v1/agent-team/sessions/session-1/tool-approvals")

    assert listed.status_code == 200
    assert listed.json() == {
        "approvals": [
            {
                "request_id": "approval-1",
                "session_id": "session-1",
                "agent_id": "agent-1",
                "tool_name": "workspace.write",
                "tool_args": {"path": "src/example.py"},
                "risk_level": "high",
                "status": "pending",
                "submitted_at": 10.0,
                "timeout_at": 20.0,
                "decided_by": None,
            }
        ],
        "items": [
            {
                "request_id": "approval-1",
                "session_id": "session-1",
                "agent_id": "agent-1",
                "tool_name": "workspace.write",
                "tool_args": {"path": "src/example.py"},
                "risk_level": "high",
                "status": "pending",
                "submitted_at": 10.0,
                "timeout_at": 20.0,
                "decided_by": None,
            }
        ],
        "count": 1,
    }

    approved = client.post(
        "/v1/agent-team/sessions/session-1/tool-approvals/approval-1/approve",
        json={"reason": "Reviewed"},
    )

    assert approved.status_code == 200
    assert approved.json()["approval"]["status"] == "approved"
    assert approved.json()["approval"]["decided_by"] == "user-1"

    paths = client.get("/openapi.json").json()["paths"]
    assert set(paths["/v1/agent-team/sessions/{session_id}/tool-approvals"]) == {"get"}
    assert set(
        paths["/v1/agent-team/sessions/{session_id}/tool-approvals/{request_id}/decision"]
    ) == {"post"}
    assert set(
        paths["/v1/agent-team/sessions/{session_id}/tool-approvals/{request_id}/approve"]
    ) == {"post"}
    assert (
        paths["/v1/agent-team/sessions/{session_id}/tool-approvals"]["get"]["responses"]["200"][
            "content"
        ]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/AgentTeamToolApprovalListResponse"
    )


def test_tool_approval_subrouter_uses_root_router_patch_seams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = FakeAgentTeamService()
    client = _client(service)
    runtime = SimpleNamespace(agent_team_service=service)
    calls: list[object] = []

    def service_or_503(received_runtime: object) -> FakeAgentTeamService:
        calls.append(received_runtime)
        return service

    monkeypatch.setattr(agent_team, "_agent_team_service_or_503", service_or_503)
    monkeypatch.setattr(
        agent_team,
        "_agent_team_error",
        lambda exc: HTTPException(status_code=418, detail=f"mapped:{exc}"),
    )

    listed = client.get("/v1/agent-team/sessions/session-1/tool-approvals")
    missing = client.get("/v1/agent-team/sessions/missing/tool-approvals")

    assert listed.status_code == 200
    assert calls
    assert all(call.agent_team_service is service for call in calls)
    assert runtime.agent_team_service is service
    assert missing.status_code == 418
    assert missing.json()["detail"] == "mapped:'missing'"
