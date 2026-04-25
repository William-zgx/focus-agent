from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from focus_agent.api.main import create_app
from focus_agent.repositories.sqlite_agent_team_repository import SQLiteAgentTeamRepository
from focus_agent.services.agent_team import AgentTeamService


def _client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    agent_team_service: AgentTeamService | None = None,
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
        agent_team_service=agent_team_service or AgentTeamService(branch_service=None),
    )
    return TestClient(app)


def test_agent_team_api_session_task_output_merge_flow(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)

    created = client.post(
        "/v1/agent-team/sessions",
        json={"root_thread_id": "root-1", "goal": "Build Agent Team Workbench"},
    )
    assert created.status_code == 200
    session_id = created.json()["session"]["session_id"]

    task_response = client.post(
        f"/v1/agent-team/sessions/{session_id}/tasks",
        json={"role": "backend_executor", "goal": "Implement backend", "create_branch": False},
    )
    assert task_response.status_code == 200
    task_id = task_response.json()["task"]["task_id"]

    output_response = client.post(
        f"/v1/agent-team/tasks/{task_id}/outputs",
        json={
            "kind": "patch_summary",
            "artifact_id": "artifact-1",
            "summary": "Backend routes and service implemented.",
            "changed_files": ["src/focus_agent/services/agent_team.py"],
            "test_evidence": ["pytest tests/test_agent_team_api.py"],
        },
    )
    assert output_response.status_code == 200

    update_response = client.post(
        f"/v1/agent-team/tasks/{task_id}/status",
        json={"status": "done"},
    )
    assert update_response.status_code == 200

    bundle_response = client.post(f"/v1/agent-team/sessions/{session_id}/merge-proposal")
    assert bundle_response.status_code == 200
    bundle = bundle_response.json()["bundle"]
    assert bundle["accepted_tasks"] == [task_id]
    assert bundle["recommended_next_action"] == "merge"

    decision_response = client.post(
        f"/v1/agent-team/sessions/{session_id}/merge",
        json={"apply": False, "next_action": "split_followup", "rationale": "MVP backend accepted"},
    )
    assert decision_response.status_code == 200
    assert decision_response.json()["decision"]["accepted_tasks"] == [task_id]
    assert decision_response.json()["applied"] is False
    assert decision_response.json()["decision"]["action"] == "split_followup"


def test_agent_team_api_dispatches_default_tasks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)

    created = client.post(
        "/v1/agent-team/sessions",
        json={"root_thread_id": "root-1", "goal": "Build Agent Team Workbench"},
    )
    assert created.status_code == 200
    session_id = created.json()["session"]["session_id"]

    dispatch_response = client.post(
        f"/v1/agent-team/sessions/{session_id}/dispatch",
        json={"create_branches": False},
    )
    assert dispatch_response.status_code == 200
    dispatch_payload = dispatch_response.json()
    assert dispatch_payload["session"]["status"] == "running"
    assert dispatch_payload["count"] == 6
    assert [task["role"] for task in dispatch_payload["tasks"]] == [
        "planner",
        "backend_executor",
        "frontend_executor",
        "test_engineer",
        "reviewer",
        "verifier",
    ]
    assert dispatch_payload["tasks"][0]["status"] == "running"


def test_agent_team_api_persists_default_dispatch_bundle_across_runtime_rebuild(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "agent-team.sqlite3"
    client = _client(
        monkeypatch,
        tmp_path,
        agent_team_service=AgentTeamService(
            branch_service=None,
            repository=SQLiteAgentTeamRepository(str(db_path)),
        ),
    )

    created = client.post(
        "/v1/agent-team/sessions",
        json={"root_thread_id": "root-1", "goal": "Persist default dispatch"},
    )
    assert created.status_code == 200
    session_id = created.json()["session"]["session_id"]

    dispatch_response = client.post(
        f"/v1/agent-team/sessions/{session_id}/dispatch",
        json={"create_branches": False},
    )
    assert dispatch_response.status_code == 200
    dispatched_tasks = dispatch_response.json()["tasks"]
    assert len(dispatched_tasks) == 6

    bundle_response = client.post(f"/v1/agent-team/sessions/{session_id}/merge-bundle")
    assert bundle_response.status_code == 200
    bundle = bundle_response.json()["bundle"]
    assert bundle["session_id"] == session_id
    assert bundle["recommended_next_action"] == "split_followup"

    reloaded_client = _client(
        monkeypatch,
        tmp_path,
        agent_team_service=AgentTeamService(
            branch_service=None,
            repository=SQLiteAgentTeamRepository(str(db_path)),
        ),
    )

    restored_response = reloaded_client.get(f"/v1/agent-team/sessions/{session_id}")
    assert restored_response.status_code == 200
    restored_session = restored_response.json()["session"]
    assert restored_session["status"] == "awaiting_review"
    assert restored_session["latest_merge_bundle"]["session_id"] == session_id
    assert restored_session["latest_merge_bundle"]["recommended_next_action"] == "split_followup"

    tasks_response = reloaded_client.get(f"/v1/agent-team/sessions/{session_id}/tasks")
    assert tasks_response.status_code == 200
    restored_tasks = tasks_response.json()["tasks"]
    assert [task["role"] for task in restored_tasks] == [
        "planner",
        "backend_executor",
        "frontend_executor",
        "test_engineer",
        "reviewer",
        "verifier",
    ]
    assert restored_tasks[0]["status"] == "running"


def test_agent_team_api_missing_session_returns_404(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)

    get_response = client.get("/v1/agent-team/sessions/missing-session")
    assert get_response.status_code == 404

    dispatch_response = client.post(
        "/v1/agent-team/sessions/missing-session/dispatch",
        json={"create_branches": False},
    )
    assert dispatch_response.status_code == 404

    bundle_response = client.post("/v1/agent-team/sessions/missing-session/merge-bundle")
    assert bundle_response.status_code == 404
