from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from focus_agent.api.main import create_app
from focus_agent.core.agent_team import AgentTeamTaskStatus
from focus_agent.repositories.sqlite_agent_team_repository import SQLiteAgentTeamRepository
from focus_agent.services.agent_team import AgentTeamService


class RecordingBackgroundWork:
    def __init__(self) -> None:
        self.submissions: list[dict[str, object]] = []

    def submit(self, *, key: str, func: object, **kwargs: object) -> bool:
        self.submissions.append({"key": key, "func": func, "kwargs": kwargs})
        return True


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


def test_agent_team_api_session_task_output_merge_flow(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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
    task_payload = task_response.json()["task"]
    assert task_payload["agent_run_id"] is None
    assert task_payload["delegated_task_id"] is None
    assert task_payload["artifact_ids"] == []
    assert task_payload["execution_status"] is None
    task_id = task_payload["task_id"]

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
    assert bundle["execution_evidence"] == []

    decision_response = client.post(
        f"/v1/agent-team/sessions/{session_id}/merge",
        json={"apply": False, "next_action": "split_followup", "rationale": "MVP backend accepted"},
    )
    assert decision_response.status_code == 200
    assert decision_response.json()["decision"]["accepted_tasks"] == [task_id]
    assert decision_response.json()["applied"] is False
    assert decision_response.json()["decision"]["action"] == "split_followup"


def test_agent_team_api_dispatches_default_tasks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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


def test_agent_team_api_plan_run_view_and_list_filters(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _client(monkeypatch, tmp_path)

    first = client.post(
        "/v1/agent-team/sessions",
        json={"root_thread_id": "root-1", "goal": "First backend task"},
    ).json()["session"]
    second = client.post(
        "/v1/agent-team/sessions",
        json={"root_thread_id": "root-2", "goal": "Second backend task"},
    ).json()["session"]

    plan_response = client.post(
        f"/v1/agent-team/sessions/{first['session_id']}/plan",
        json={"create_branches": False},
    )
    assert plan_response.status_code == 200
    plan_payload = plan_response.json()
    assert 1 <= plan_payload["count"] <= 6
    assert plan_payload["planning"]["source"] == "model"
    assert plan_payload["planning"]["error"] is None
    assert [task["role"] for task in plan_payload["tasks"]] != [
        "planner",
        "backend_executor",
        "frontend_executor",
        "test_engineer",
        "reviewer",
        "verifier",
    ]

    list_response = client.get("/v1/agent-team/sessions", params={"root_thread_id": "root-1"})
    assert list_response.status_code == 200
    assert [item["session_id"] for item in list_response.json()["sessions"]] == [
        first["session_id"]
    ]

    paged_response = client.get("/v1/agent-team/sessions", params={"limit": 1})
    assert paged_response.status_code == 200
    assert paged_response.json()["count"] == 1
    assert paged_response.json()["sessions"][0]["session_id"] == second["session_id"]

    task_response = client.post(
        f"/v1/agent-team/sessions/{second['session_id']}/tasks",
        json={
            "role": "backend_executor",
            "goal": "Execute fake backend run",
            "acceptance_criteria": ["Fake execution evidence is stored."],
            "context_refs": [{"kind": "thread", "id": "root-2"}],
            "create_branch": False,
        },
    )
    assert task_response.status_code == 200
    task_id = task_response.json()["task"]["task_id"]

    run_response = client.post(f"/v1/agent-team/sessions/{second['session_id']}/run")
    assert run_response.status_code == 200
    run_task = run_response.json()["tasks"][0]
    assert run_task["task_id"] == task_id
    assert run_task["status"] == "done"
    assert run_task["run_status"] == "completed"
    assert run_task["agent_run_id"] == f"run-{task_id}"
    assert run_task["artifact_ids"] == [f"artifact-{task_id}-fake-result"]

    view_response = client.get(f"/v1/agent-team/sessions/{second['session_id']}/view")
    assert view_response.status_code == 200
    view = view_response.json()
    assert view["session"]["session_id"] == second["session_id"]
    assert view["outputs"][0]["metadata"]["execution"]["agent_run_id"] == f"run-{task_id}"
    assert view["artifacts"][0]["payload"]["context_refs"] == [{"kind": "thread", "id": "root-2"}]


def test_agent_team_api_task_run_respects_dependencies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _client(monkeypatch, tmp_path)
    session_id = client.post(
        "/v1/agent-team/sessions",
        json={"root_thread_id": "root-1", "goal": "Dependency run"},
    ).json()["session"]["session_id"]
    dependency_id = client.post(
        f"/v1/agent-team/sessions/{session_id}/tasks",
        json={"role": "backend_executor", "goal": "Implement backend", "create_branch": False},
    ).json()["task"]["task_id"]
    blocked_id = client.post(
        f"/v1/agent-team/sessions/{session_id}/tasks",
        json={
            "role": "test_engineer",
            "goal": "Verify backend",
            "dependencies": [dependency_id],
            "create_branch": False,
        },
    ).json()["task"]["task_id"]

    run_response = client.post(f"/v1/agent-team/tasks/{blocked_id}/run")

    assert run_response.status_code == 200
    assert run_response.json()["task"]["status"] == "pending"


def test_agent_team_api_retry_keeps_unsatisfied_dependency_pending(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    background_work = RecordingBackgroundWork()
    service = AgentTeamService(branch_service=None, background_work=background_work)
    client = _client(monkeypatch, tmp_path, agent_team_service=service)
    session_id = client.post(
        "/v1/agent-team/sessions",
        json={"root_thread_id": "root-1", "goal": "Retry dependency gate"},
    ).json()["session"]["session_id"]
    dependency_id = client.post(
        f"/v1/agent-team/sessions/{session_id}/tasks",
        json={"role": "backend_executor", "goal": "Must finish first", "create_branch": False},
    ).json()["task"]["task_id"]
    blocked_id = client.post(
        f"/v1/agent-team/sessions/{session_id}/tasks",
        json={
            "role": "test_engineer",
            "goal": "Retry should wait",
            "dependencies": [dependency_id],
            "create_branch": False,
        },
    ).json()["task"]["task_id"]
    service.update_task(
        task_id=blocked_id,
        user_id="anonymous",
        status=AgentTeamTaskStatus.BLOCKED,
        last_error="dependency failed",
    )

    retry_response = client.post(f"/v1/agent-team/tasks/{blocked_id}/retry")

    assert retry_response.status_code == 200
    retried = retry_response.json()["task"]
    assert retried["status"] == "pending"
    assert retried["run_status"] is None
    assert retried["execution_status"] is None
    assert background_work.submissions == []


def test_agent_team_task_claim_lost_does_not_persist_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = AgentTeamService(branch_service=None)
    session = service.create_session(
        root_thread_id="root-1",
        goal="Lost claim should not commit",
        user_id="anonymous",
    )
    task = service.create_task(
        session_id=session.session_id,
        user_id="anonymous",
        role="backend_executor",
        goal="Produce fake output",
        create_branch=False,
    )
    service.run_task(task_id=task.task_id, user_id="anonymous")
    queued = service.get_task(task.task_id, user_id="anonymous")
    assert queued.status == AgentTeamTaskStatus.DONE

    task = service.create_task(
        session_id=session.session_id,
        user_id="anonymous",
        role="reviewer",
        goal="Lose claim before commit",
        create_branch=False,
    )
    service.update_task(
        task_id=task.task_id,
        user_id="anonymous",
        status=AgentTeamTaskStatus.QUEUED,
        run_status="queued",
        execution_status="queued",
    )
    monkeypatch.setattr(service.repository, "heartbeat_task_claim", lambda **_: False)

    result = service.run_task_claimed(task_id=task.task_id, user_id="anonymous")

    assert result.status == AgentTeamTaskStatus.FAILED
    assert result.last_error == "Task claim was lost before completion could be committed."
    assert service.list_task_outputs(task_id=task.task_id, user_id="anonymous") == []
    reloaded = service.get_task(task.task_id, user_id="anonymous")
    assert reloaded.agent_run_id is None
    assert reloaded.artifact_ids == []


def test_agent_team_api_session_run_returns_queued_running_view_and_waiting_dependencies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    background_work = RecordingBackgroundWork()
    service = AgentTeamService(branch_service=None, background_work=background_work)
    client = _client(monkeypatch, tmp_path, agent_team_service=service)
    session_id = client.post(
        "/v1/agent-team/sessions",
        json={"root_thread_id": "root-1", "goal": "Queue runnable tasks"},
    ).json()["session"]["session_id"]
    queued_candidate_id = client.post(
        f"/v1/agent-team/sessions/{session_id}/tasks",
        json={"role": "backend_executor", "goal": "Queue this task", "create_branch": False},
    ).json()["task"]["task_id"]
    running_id = client.post(
        f"/v1/agent-team/sessions/{session_id}/tasks",
        json={"role": "reviewer", "goal": "Already running", "create_branch": False},
    ).json()["task"]["task_id"]
    waiting_id = client.post(
        f"/v1/agent-team/sessions/{session_id}/tasks",
        json={
            "role": "test_engineer",
            "goal": "Wait for queued task",
            "dependencies": [queued_candidate_id],
            "create_branch": False,
        },
    ).json()["task"]["task_id"]
    service.update_task(
        task_id=running_id,
        user_id="anonymous",
        status=AgentTeamTaskStatus.RUNNING,
        run_status="running",
    )

    run_response = client.post(f"/v1/agent-team/sessions/{session_id}/run")

    assert run_response.status_code == 200
    view = run_response.json()
    by_id = {task["task_id"]: task for task in view["tasks"]}
    assert by_id[queued_candidate_id]["status"] == "queued"
    assert by_id[queued_candidate_id]["run_status"] == "queued"
    assert by_id[queued_candidate_id]["execution_status"] == "queued"
    assert by_id[running_id]["status"] == "running"
    assert by_id[running_id]["run_status"] == "running"
    assert by_id[waiting_id]["status"] == "pending"
    assert view["run"]["scheduled_task_ids"] == [queued_candidate_id, running_id]
    assert view["run"]["running_task_ids"] == [running_id]
    assert [item["key"] for item in background_work.submissions] == [
        f"agent-team:task:{queued_candidate_id}"
    ]
    assert [item["kwargs"] for item in background_work.submissions] == [
        {"task_id": queued_candidate_id, "user_id": "anonymous"}
    ]


def test_agent_team_api_run_does_not_revive_cancelled_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    background_work = RecordingBackgroundWork()
    service = AgentTeamService(branch_service=None, background_work=background_work)
    client = _client(monkeypatch, tmp_path, agent_team_service=service)
    session_id = client.post(
        "/v1/agent-team/sessions",
        json={"root_thread_id": "root-1", "goal": "Do not revive cancelled session"},
    ).json()["session"]["session_id"]
    client.post(
        f"/v1/agent-team/sessions/{session_id}/tasks",
        json={"role": "backend_executor", "goal": "Remain cancelled", "create_branch": False},
    )
    assert client.post(f"/v1/agent-team/sessions/{session_id}/cancel").status_code == 200

    run_response = client.post(f"/v1/agent-team/sessions/{session_id}/run")

    assert run_response.status_code == 200
    view = run_response.json()
    assert view["session"]["status"] == "cancelled"
    assert [task["status"] for task in view["tasks"]] == ["cancelled"]
    assert background_work.submissions == []


def test_agent_team_api_session_run_honors_parallel_capacity_and_task_ids(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    background_work = RecordingBackgroundWork()
    service = AgentTeamService(
        branch_service=None,
        background_work=background_work,
        settings=SimpleNamespace(agent_role_max_parallel_runs=2),
    )
    client = _client(monkeypatch, tmp_path, agent_team_service=service)
    session_id = client.post(
        "/v1/agent-team/sessions",
        json={"root_thread_id": "root-1", "goal": "Respect capacity and selected tasks"},
    ).json()["session"]["session_id"]
    ids = [
        client.post(
            f"/v1/agent-team/sessions/{session_id}/tasks",
            json={"role": "backend_executor", "goal": f"Task {index}", "create_branch": False},
        ).json()["task"]["task_id"]
        for index in range(3)
    ]
    service.update_task(
        task_id=ids[0],
        user_id="anonymous",
        status=AgentTeamTaskStatus.RUNNING,
        run_status="running",
    )

    run_response = client.post(
        f"/v1/agent-team/sessions/{session_id}/run",
        json={"task_ids": [ids[2]]},
    )

    assert run_response.status_code == 200
    by_id = {task["task_id"]: task for task in run_response.json()["tasks"]}
    assert by_id[ids[0]]["status"] == "running"
    assert by_id[ids[1]]["status"] == "pending"
    assert by_id[ids[2]]["status"] == "queued"
    assert len(background_work.submissions) == 1
    assert background_work.submissions[0]["key"] == f"agent-team:task:{ids[2]}"


def test_agent_team_api_task_retry_cancel_and_session_cancel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    background_work = RecordingBackgroundWork()
    service = AgentTeamService(branch_service=None, background_work=background_work)
    client = _client(monkeypatch, tmp_path, agent_team_service=service)
    session_id = client.post(
        "/v1/agent-team/sessions",
        json={"root_thread_id": "root-1", "goal": "Cancel and retry tasks"},
    ).json()["session"]["session_id"]
    retry_id = client.post(
        f"/v1/agent-team/sessions/{session_id}/tasks",
        json={"role": "backend_executor", "goal": "Retry failed work", "create_branch": False},
    ).json()["task"]["task_id"]
    running_id = client.post(
        f"/v1/agent-team/sessions/{session_id}/tasks",
        json={"role": "reviewer", "goal": "Cancel running work", "create_branch": False},
    ).json()["task"]["task_id"]
    pending_id = client.post(
        f"/v1/agent-team/sessions/{session_id}/tasks",
        json={"role": "verifier", "goal": "Cancel pending work", "create_branch": False},
    ).json()["task"]["task_id"]
    service.update_task(
        task_id=retry_id,
        user_id="anonymous",
        status=AgentTeamTaskStatus.FAILED,
        last_error="boom",
    )
    service.update_task(
        task_id=running_id,
        user_id="anonymous",
        status=AgentTeamTaskStatus.RUNNING,
        run_status="running",
    )

    retry_response = client.post(f"/v1/agent-team/tasks/{retry_id}/retry")
    cancel_queued_response = client.post(f"/v1/agent-team/tasks/{retry_id}/cancel")
    cancel_running_response = client.post(f"/v1/agent-team/tasks/{running_id}/cancel")
    session_cancel_response = client.post(f"/v1/agent-team/sessions/{session_id}/cancel")

    assert retry_response.status_code == 200
    retried = retry_response.json()["task"]
    assert retried["status"] == "queued"
    assert retried["run_status"] == "queued"
    assert retried["execution_status"] == "queued"
    assert retried["last_error"] == ""

    assert cancel_queued_response.status_code == 200
    cancelled_queued = cancel_queued_response.json()["task"]
    assert cancelled_queued["status"] == "cancelled"
    assert cancelled_queued["run_status"] == "cancelled"
    assert cancelled_queued["execution_status"] == "cancel_requested"
    assert cancelled_queued["cancel_requested_at"] is not None

    assert cancel_running_response.status_code == 200
    cancelled_running = cancel_running_response.json()["task"]
    assert cancelled_running["status"] == "running"
    assert cancelled_running["run_status"] == "running"
    assert cancelled_running["execution_status"] == "cancel_requested"
    assert cancelled_running["cancel_requested_at"] is not None

    assert session_cancel_response.status_code == 200
    view = session_cancel_response.json()
    by_id = {task["task_id"]: task for task in view["tasks"]}
    assert view["session"]["status"] == "cancelled"
    assert by_id[pending_id]["status"] == "cancelled"
    assert by_id[pending_id]["run_status"] == "cancelled"
    assert by_id[running_id]["status"] == "running"
    assert by_id[running_id]["execution_status"] == "cancel_requested"


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
    assert bundle["recommended_next_action"] == "request_changes"

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
    assert restored_session["latest_merge_bundle"]["recommended_next_action"] == "request_changes"

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


def test_agent_team_api_missing_session_returns_404(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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
