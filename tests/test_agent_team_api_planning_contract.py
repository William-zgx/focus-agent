from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from focus_agent.api.main import create_app
from focus_agent.services.agent_team import AgentTeamService


class CapturingPlanAgentTeamService(AgentTeamService):
    def __init__(self) -> None:
        super().__init__(branch_service=None)
        self.plan_kwargs: dict[str, Any] = {}

    def plan_session(self, **kwargs: Any):
        self.plan_kwargs = dict(kwargs)
        return self.dispatch_default_tasks(
            session_id=str(kwargs["session_id"]),
            user_id=str(kwargs["user_id"]),
            create_branches=bool(kwargs.get("create_branches")),
            parent_thread_id=kwargs.get("parent_thread_id"),
        )


def _client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    agent_team_service: AgentTeamService,
) -> TestClient:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "test-api-key")
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("WEB_APP_DIST_DIR", str(dist_dir))
    monkeypatch.setenv("WEB_APP_DEV_SERVER_URL", "")
    app = create_app()
    app.state.runtime = SimpleNamespace(
        settings=SimpleNamespace(auth_enabled=False, model="openai:gpt-4.1-mini"),
        agent_team_service=agent_team_service,
    )
    return TestClient(app)


def test_agent_team_plan_request_fields_are_forwarded_and_view_exposes_planning_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = CapturingPlanAgentTeamService()
    client = _client(monkeypatch, tmp_path, service)
    session = client.post(
        "/v1/agent-team/sessions",
        json={"root_thread_id": "root-1", "goal": "Plan a goal-driven Agent Team run"},
    ).json()["session"]

    plan_response = client.post(
        f"/v1/agent-team/sessions/{session['session_id']}/plan",
        json={
            "create_branches": True,
            "auto_fork_branch": False,
            "parent_thread_id": "parent-1",
            "replace_existing": True,
            "granularity": "detailed",
            "focus": "verification",
            "max_tasks": 4,
        },
    )

    assert plan_response.status_code == 200
    assert service.plan_kwargs["create_branches"] is False
    assert service.plan_kwargs["parent_thread_id"] == "parent-1"
    assert service.plan_kwargs["replace_existing"] is True
    assert service.plan_kwargs["granularity"] == "detailed"
    assert service.plan_kwargs["focus"] == "verification"
    assert service.plan_kwargs["max_tasks"] == 4
    assert plan_response.json()["planning"]["source"] == "legacy_template"
    assert plan_response.json()["planning"]["task_count"] == 6

    view_response = client.get(f"/v1/agent-team/sessions/{session['session_id']}/view")

    assert view_response.status_code == 200
    planning = view_response.json()["planning"]
    assert set(planning) == {
        "source",
        "rationale",
        "planner_model_id",
        "generated_at",
        "plan_hash",
        "error",
        "task_count",
    }
    assert planning["task_count"] == 6
