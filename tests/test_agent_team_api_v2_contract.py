from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from focus_agent.api.deps import get_current_principal
from focus_agent.api.main import create_app
from focus_agent.config import ConfiguredModel, ModelCatalogConfig, ProviderConfig
from focus_agent.core.agent_team import (
    AgentTeamEvidenceLevel,
    AgentTeamEvidenceVerdict,
    AgentTeamExecutionClass,
    EvidenceRecord,
    TaskRun,
)
from focus_agent.security.tokens import Principal
from focus_agent.services.agent_team import AgentTeamService

ROOT = Path(__file__).resolve().parents[1]
SDK_ROOT = ROOT / "frontend-sdk"


def _v2_settings(**overrides: object) -> SimpleNamespace:
    values = {
        "agent_team_v2_enabled": True,
        "multi_agent_v2_enabled": True,
        "agent_team_rollout_phase": "canary",
        "agent_team_execution_mode": "disabled",
        "agent_team_kill_switch_enabled": False,
        "agent_team_legacy_write_enabled": False,
        "agent_team_approval_resume_enabled": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class _HealthyDurableWorker:
    def snapshot(self) -> dict[str, int]:
        return {
            "durable_worker_started": 1,
            "durable_worker_thread_alive": 1,
            "durable_worker_heartbeat_fresh": 1,
        }


def _git(cwd: Path, *args: str) -> None:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def _ready_v2_settings(workspace_root: Path) -> SimpleNamespace:
    model_catalog = ModelCatalogConfig(
        default_model="openai:gpt-4.1-mini",
        providers=(ProviderConfig(id="openai", api_key_env="OPENAI_API_KEY"),),
        models=(ConfiguredModel(id="openai:gpt-4.1-mini"),),
    )
    return _v2_settings(
        agent_team_execution_mode="worktree_sandbox",
        agent_delegation_execution_mode="background",
        agent_team_real_provider_enabled=True,
        agent_team_durable_required=True,
        agent_team_fencing_enabled=True,
        agent_team_cross_session_locks_enabled=True,
        multi_agent_resource_lock_enabled=True,
        background_job_backend="postgres",
        background_job_execution="durable",
        database_uri="postgresql://focus-agent.test/readiness",
        model="openai:gpt-4.1-mini",
        model_catalog=model_catalog,
        workspace_root=str(workspace_root),
        resolved_env={
            "OPENAI_API_KEY": "test-key",
            "FOCUS_AGENT_SANDBOX_BACKEND": "docker",
            "FOCUS_AGENT_SANDBOX_ALLOW_LOCAL_FALLBACK": "0",
        },
    )


def _seed_execution_records(
    service: AgentTeamService,
    *,
    user_id: str = "anonymous",
    execution_class: AgentTeamExecutionClass | None = AgentTeamExecutionClass.TOOL_AGENT,
) -> tuple[str, str]:
    session = service.create_session(user_id=user_id, goal="Agent Team v2 contract test")
    task = service.create_task(
        session_id=session.session_id,
        user_id=user_id,
        role="backend_executor",
        goal="Verify v2 execution records.",
    )
    task_run = TaskRun(
        task_run_id="run-1",
        task_id=task.task_id,
        session_id=session.session_id,
        status="running",
        attempt=1,
        execution_class=execution_class,
        evidence_level=AgentTeamEvidenceLevel.MODEL,
        evidence_verdict=AgentTeamEvidenceVerdict.INCONCLUSIVE,
        metadata={"provider": "test"},
        created_at="2026-07-13T00:00:00+00:00",
    )
    evidence = EvidenceRecord(
        evidence_id="evidence-1",
        task_run_id=task_run.task_run_id,
        task_id=task.task_id,
        session_id=session.session_id,
        source_type="test",
        summary="pytest passed",
        execution_class=execution_class,
        evidence_level=AgentTeamEvidenceLevel.MODEL,
        evidence_verdict=AgentTeamEvidenceVerdict.INCONCLUSIVE,
        metadata={"command": "pytest"},
        created_at="2026-07-13T00:00:01+00:00",
    )
    service.repository.create_task_run(task_run)
    service.repository.add_evidence_record(evidence)
    return session.session_id, task.task_id


def _client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    service: AgentTeamService | None = None,
    principal: Principal | None = None,
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
        agent_team_service=service or AgentTeamService(branch_service=None),
    )
    if principal is not None:
        app.dependency_overrides[get_current_principal] = lambda: principal
    return TestClient(app)


def test_agent_team_v2_readiness_and_unsupported_capabilities_are_explicit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _client(monkeypatch, tmp_path)

    readiness = client.get("/v2/agent-team/readiness")
    task_runs = client.get("/v2/agent-team/tasks/task-1/runs")

    assert readiness.status_code == 200
    assert readiness.json() == {
        "status": "disabled",
        "ready": False,
        "enabled": False,
        "service_available": True,
        "capabilities": {
            "task_run_queries": True,
            "evidence_queries": True,
            "revision_commands": False,
        },
        "detail": "Agent Team v2 rollout is disabled by configuration.",
    }
    assert task_runs.status_code == 404


def test_agent_team_v2_queries_use_real_service_records_and_preserve_ownership(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = AgentTeamService(branch_service=None, settings=_v2_settings())
    session_id, task_id = _seed_execution_records(service)
    client = _client(monkeypatch, tmp_path, service)

    readiness = client.get("/v2/agent-team/readiness")
    task_run = client.get("/v2/agent-team/task-runs/run-1")
    task_runs = client.get(f"/v2/agent-team/tasks/{task_id}/runs")
    evidence = client.get(f"/v2/agent-team/sessions/{session_id}/evidence")
    command = client.post(
        f"/v2/agent-team/sessions/{session_id}/revisions/commands",
        json={
            "command": "create",
            "revision_id": "revision-2",
            "parent_revision_id": "revision-1",
            "task_ids": [task_id],
            "metadata": {"reason": "scope change"},
        },
    )

    assert readiness.status_code == 200
    assert readiness.json()["status"] == "degraded"
    assert readiness.json()["ready"] is False
    assert readiness.json()["capabilities"] == {
        "task_run_queries": True,
        "evidence_queries": True,
        "revision_commands": False,
    }
    assert task_run.status_code == 200
    assert task_run.json()["task_run"]["task_run_id"] == "run-1"
    assert task_run.json()["task_run"]["metadata"] == {"provider": "test"}
    assert task_runs.status_code == 200
    assert task_runs.json()["count"] == 1
    assert evidence.status_code == 200
    assert evidence.json()["items"][0]["evidence_id"] == "evidence-1"
    assert command.status_code == 501
    assert command.json()["message"] == (
        "Agent Team v2 capability 'execute_revision_command' is not implemented by this service."
    )


def test_agent_team_v2_legacy_records_preserve_missing_execution_class(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = AgentTeamService(branch_service=None, settings=_v2_settings())
    session_id, task_id = _seed_execution_records(service, execution_class=None)
    client = _client(monkeypatch, tmp_path, service)

    get_task_run = client.get("/v2/agent-team/task-runs/run-1")
    list_task_runs = client.get(f"/v2/agent-team/tasks/{task_id}/runs")
    list_evidence = client.get(f"/v2/agent-team/sessions/{session_id}/evidence")

    assert get_task_run.status_code == 200
    assert get_task_run.json()["task_run"]["execution_class"] is None
    assert list_task_runs.status_code == 200
    assert list_task_runs.json()["items"][0]["execution_class"] is None
    assert list_evidence.status_code == 200
    assert list_evidence.json()["items"][0]["execution_class"] is None


def test_agent_team_v2_records_reject_cross_user_access_and_invalid_revision_task(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = AgentTeamService(branch_service=None, settings=_v2_settings())
    session_id, task_id = _seed_execution_records(service)
    assert service.get_task_run(task_run_id="run-1", user_id="anonymous").task_id == task_id
    with pytest.raises(PermissionError):
        service.get_task_run(task_run_id="run-1", user_id="other")
    with pytest.raises(PermissionError):
        service.list_task_runs(task_id=task_id, user_id="other")
    with pytest.raises(PermissionError):
        service.list_evidence_records(session_id=session_id, user_id="other")
    other_session = service.create_session(user_id="anonymous", goal="Other session")
    other_task = service.create_task(
        session_id=other_session.session_id,
        user_id="anonymous",
        role="reviewer",
        goal="Verify ownership checks.",
    )
    client = _client(monkeypatch, tmp_path, service)

    response = client.post(
        f"/v2/agent-team/sessions/{session_id}/revisions/commands",
        json={"command": "create", "task_ids": [other_task.task_id]},
    )

    assert response.status_code == 400
    assert response.json()["message"] == (
        f"Task does not belong to this session: {other_task.task_id}"
    )


def test_agent_team_v2_ownership_errors_map_to_403_at_the_api_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = AgentTeamService(branch_service=None, settings=_v2_settings())
    session_id, task_id = _seed_execution_records(service, user_id="owner")
    owner_client = _client(
        monkeypatch,
        tmp_path,
        service,
        principal=Principal(user_id="owner"),
    )
    intruder_client = _client(
        monkeypatch,
        tmp_path,
        service,
        principal=Principal(user_id="intruder"),
    )

    assert owner_client.get("/v2/agent-team/task-runs/run-1").status_code == 200
    assert owner_client.get(f"/v2/agent-team/tasks/{task_id}/runs").status_code == 200
    assert owner_client.get(f"/v2/agent-team/sessions/{session_id}/evidence").status_code == 200

    task_run = intruder_client.get("/v2/agent-team/task-runs/run-1")
    task_runs = intruder_client.get(f"/v2/agent-team/tasks/{task_id}/runs")
    evidence = intruder_client.get(f"/v2/agent-team/sessions/{session_id}/evidence")

    assert task_run.status_code == 403
    assert task_runs.status_code == 403
    assert evidence.status_code == 403
    assert task_run.json()["message"] == "Agent team session belongs to another user."
    assert evidence.json()["message"] == "Agent team session belongs to another user."


def test_agent_team_v2_readiness_uses_builder_and_does_not_leak_secrets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = _v2_settings(
        agent_team_execution_mode="inline",
        agent_team_kill_switch_enabled=True,
        resolved_env={"OPENAI_API_KEY": "super-secret-value"},
    )
    client = _client(
        monkeypatch, tmp_path, AgentTeamService(branch_service=None, settings=settings)
    )

    response = client.get("/v2/agent-team/readiness")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["ready"] is False
    assert "kill_switch_active" in response.json()["detail"]
    assert "super-secret-value" not in response.text


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required for workspace readiness")
def test_agent_team_v2_readiness_allows_ready_execution_without_revision_commands(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "controlled-checkout"
    workspace.mkdir()
    _git(workspace, "init")
    _git(workspace, "config", "user.email", "focus-agent@example.test")
    _git(workspace, "config", "user.name", "Focus Agent Test")
    (workspace / "README.md").write_text("workspace\n", encoding="utf-8")
    _git(workspace, "add", "README.md")
    _git(workspace, "commit", "-m", "init")
    service = AgentTeamService(
        branch_service=None,
        settings=_ready_v2_settings(workspace),
        repository=type("PostgresAgentTeamRepository", (), {})(),
    )
    runtime = SimpleNamespace(
        settings=service.settings,
        agent_team_service=service,
        durable_background_worker=_HealthyDurableWorker(),
        coordination_backend=SimpleNamespace(
            resource_locks=type("PostgresResourceLockManager", (), {})(),
            approval_queue=object(),
        ),
    )
    client = _client(monkeypatch, tmp_path, service)
    client.app.state.runtime = runtime

    response = client.get("/v2/agent-team/readiness")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["ready"] is True
    assert response.json()["capabilities"] == {
        "task_run_queries": True,
        "evidence_queries": True,
        "revision_commands": False,
    }


def test_agent_team_v2_openapi_and_sdk_shapes_are_public() -> None:
    app = create_app()
    paths = app.openapi()["paths"]
    sdk_client = (SDK_ROOT / "src" / "client" / "agent-team.ts").read_text(encoding="utf-8")
    sdk_types = (SDK_ROOT / "src" / "types" / "agent-team.ts").read_text(encoding="utf-8")

    assert {
        "/v2/agent-team/readiness",
        "/v2/agent-team/task-runs/{task_run_id}",
        "/v2/agent-team/tasks/{task_id}/runs",
        "/v2/agent-team/sessions/{session_id}/evidence",
        "/v2/agent-team/sessions/{session_id}/revisions/commands",
    }.issubset(paths)
    assert paths["/v1/agent-team/sessions"]["post"]["operationId"].startswith(
        "create_agent_team_session"
    )
    for name in [
        "FocusAgentAgentTeamReadiness",
        "FocusAgentAgentTeamTaskRun",
        "FocusAgentAgentTeamEvidence",
        "FocusAgentAgentTeamRevisionCommandRequest",
    ]:
        assert f"export interface {name}" in sdk_types or f"export type {name}" in sdk_types
    for method in [
        "getAgentTeamReadiness",
        "getAgentTeamTaskRun",
        "listAgentTeamTaskRuns",
        "listAgentTeamEvidence",
        "executeAgentTeamRevisionCommand",
    ]:
        assert method in sdk_client
