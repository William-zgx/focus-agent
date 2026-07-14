from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from langchain.messages import AIMessage

from focus_agent.config import ConfiguredModel, ModelCatalogConfig, ProviderConfig, Settings
from focus_agent.core.agent_team import (
    AgentTeamEvidenceLevel,
    AgentTeamEvidenceVerdict,
    AgentTeamExecutionClass,
    AgentTeamTaskRole,
    AgentTeamTaskStatus,
    TaskRun,
)
from focus_agent.multi_agent.approval_queue import InMemoryApprovalQueue
from focus_agent.repositories.agent_team_repository import InMemoryAgentTeamRepository
from focus_agent.services import agent_team_real_execution as real_execution_module
from focus_agent.services import agent_team_run_execution as run_execution_module
from focus_agent.services.agent_team import AgentTeamService
from focus_agent.services.agent_team_execution_runtime import (
    TaskExecutionEvidence,
    TaskExecutionScope,
    TaskModelResponse,
    TaskRunResult,
    TaskRunStatus,
    TaskToolCall,
)
from focus_agent.services.agent_team_real_execution import (
    _outcome_from_result,
    _task_scoped_tools,
    execute_real_agent_team_task,
    is_real_agent_team_execution_enabled,
)
from focus_agent.services.agent_team_run_execution import execute_task_body
from focus_agent.services.agent_team_scoped_tools import build_agent_team_scoped_tools
from focus_agent.services.agent_team_workspace import AgentTeamWorkspace, AgentTeamWorkspaceStatus


class PostgresAgentTeamRepository(InMemoryAgentTeamRepository):
    pass


class PostgresResourceLockManager:
    pass


class HealthyDurableWorker:
    def snapshot(self) -> dict[str, int]:
        return {
            "durable_worker_started": 1,
            "durable_worker_thread_alive": 1,
            "durable_worker_heartbeat_fresh": 1,
        }


class StaticWorkspaceService:
    def __init__(
        self,
        workspace_path: Path,
        *,
        status: AgentTeamWorkspaceStatus | None = None,
        status_error: Exception | None = None,
    ) -> None:
        self.workspace_path = workspace_path
        self.status = status or AgentTeamWorkspaceStatus(
            changed_files=[],
            diff_summary="",
            workspace_status="clean",
            porcelain=[],
        )
        self.status_error = status_error

    def ensure_workspace(self, *, session: Any, task: Any) -> AgentTeamWorkspace:
        return AgentTeamWorkspace(
            workspace_id=f"{session.session_id}:{task.task_id}",
            workspace_path=str(self.workspace_path),
            workspace_branch="codex/agent-team/test",
            base_commit="base-commit",
        )

    def collect_status(self, workspace_path: str) -> AgentTeamWorkspaceStatus:
        assert workspace_path == str(self.workspace_path)
        if self.status_error is not None:
            raise self.status_error
        return self.status


class CountingSandboxRunner:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    def run(self, request: Any) -> dict[str, Any]:
        self.requests.append(request)
        return {
            "status": "completed",
            "exit_code": 0,
            "timed_out": False,
            "sandbox_backend": "docker",
            "fallback_used": False,
        }


class SequencedTaskModel:
    def __init__(self, responses: list[TaskModelResponse]) -> None:
        self._responses = iter(responses)
        self.calls = 0

    def invoke(self, **_: Any) -> TaskModelResponse:
        self.calls += 1
        return next(self._responses)


class FakeLangChainModel:
    def __init__(self) -> None:
        self.bound_tool_names: list[str] = []
        self.messages: list[Any] = []

    def bind_tools(self, tools: list[Any]) -> FakeLangChainModel:
        self.bound_tool_names = [tool.name for tool in tools]
        return self

    def invoke(self, messages: list[Any]) -> AIMessage:
        self.messages = messages
        return AIMessage(content="The isolated task completed.")


class RecordingTool:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = f"{name} test tool"
        self.calls: list[dict[str, Any]] = []

    def invoke(self, arguments: dict[str, Any]) -> str:
        self.calls.append(arguments)
        return self.name


def _real_settings(workspace_root: Path | None = None) -> Settings:
    catalog = ModelCatalogConfig(
        default_model="openai:gpt-4.1-mini",
        providers=(ProviderConfig(id="openai", api_key_env="OPENAI_API_KEY"),),
        models=(ConfiguredModel(id="openai:gpt-4.1-mini"),),
    )
    return Settings(
        model_catalog=catalog,
        agent_team_v2_enabled=True,
        multi_agent_v2_enabled=True,
        multi_agent_resource_lock_enabled=True,
        agent_team_rollout_phase="canary",
        agent_team_execution_mode="worktree_sandbox",
        agent_delegation_execution_mode="background",
        agent_team_real_provider_enabled=True,
        agent_team_durable_required=True,
        agent_team_fencing_enabled=True,
        agent_team_cross_session_locks_enabled=True,
        agent_team_kill_switch_enabled=False,
        background_job_backend="postgres",
        background_job_execution="durable",
        database_uri="postgresql://focus-agent.test/agent_team",
        workspace_root=str(workspace_root) if workspace_root is not None else ".",
        resolved_env={
            "OPENAI_API_KEY": "test-key",
            "FOCUS_AGENT_SANDBOX_BACKEND": "docker",
            "FOCUS_AGENT_SANDBOX_ALLOW_LOCAL_FALLBACK": "0",
        },
    )


def _initialize_workspace(workspace_path: Path) -> None:
    workspace_path.mkdir()
    for args in (
        ("init",),
        ("config", "user.email", "focus-agent@example.test"),
        ("config", "user.name", "Focus Agent Test"),
    ):
        completed = subprocess.run(
            ["git", *args],
            cwd=workspace_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr or completed.stdout
    (workspace_path / "README.md").write_text("baseline\n", encoding="utf-8")
    for args in (("add", "README.md"), ("commit", "-m", "fixture baseline")):
        completed = subprocess.run(
            ["git", *args],
            cwd=workspace_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr or completed.stdout


def _service(
    tmp_path: Path,
    *,
    status_error: Exception | None = None,
) -> tuple[AgentTeamService, InMemoryApprovalQueue, CountingSandboxRunner]:
    workspace_path = tmp_path / "workspace"
    _initialize_workspace(workspace_path)
    queue = InMemoryApprovalQueue()
    backend = SimpleNamespace(
        resource_locks=PostgresResourceLockManager(),
        approval_queue=queue,
    )
    sandbox_runner = CountingSandboxRunner()
    service = AgentTeamService(
        branch_service=None,
        repository=PostgresAgentTeamRepository(),
        settings=_real_settings(workspace_path),
        coordination_backend=backend,
        workspace_service=StaticWorkspaceService(workspace_path, status_error=status_error),
    )
    service._agent_team_runtime = SimpleNamespace(
        agent_team_service=service,
        durable_background_worker=HealthyDurableWorker(),
        coordination_backend=backend,
    )
    service.agent_team_sandbox_runner = sandbox_runner
    return service, queue, sandbox_runner


def _task(
    service: AgentTeamService,
    *,
    role: AgentTeamTaskRole = AgentTeamTaskRole.VERIFIER,
    write_scope: list[str] | None = None,
):
    session = service.create_session(user_id="user-1", goal="Run isolated Agent Team task.")
    return service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=role,
        goal="Inspect and verify the assigned workspace.",
        write_scope=write_scope,
        create_branch=False,
    )


def _workspace_metadata(task: Any, workspace_path: Path) -> dict[str, str]:
    return {
        "workspace_id": f"{task.session_id}:{task.task_id}",
        "workspace_path": str(workspace_path),
        "workspace_branch": "codex/agent-team/test",
        "base_commit": "base-commit",
    }


def _running_task_run(task: Any) -> TaskRun:
    now = datetime.now(UTC).isoformat()
    return TaskRun(
        task_run_id="task-run-verified",
        task_id=task.task_id,
        session_id=task.session_id,
        status=AgentTeamTaskStatus.RUNNING,
        started_at=now,
        execution_profile="worktree_sandbox",
        execution_class=AgentTeamExecutionClass.TOOL_AGENT,
        evidence_level=AgentTeamEvidenceLevel.WORKTREE,
        evidence_verdict=AgentTeamEvidenceVerdict.INCONCLUSIVE,
        sandbox_id="agent-team:test",
        created_at=now,
        updated_at=now,
    )


def test_real_execution_requires_injected_runtime_readiness(tmp_path: Path) -> None:
    service, _, _ = _service(tmp_path)
    settings = service.settings
    del service._agent_team_runtime

    assert is_real_agent_team_execution_enabled(settings) is False
    assert is_real_agent_team_execution_enabled(settings, service=service) is False

    service._agent_team_runtime = SimpleNamespace(
        agent_team_service=service,
        durable_background_worker=HealthyDurableWorker(),
        coordination_backend=service.coordination_backend,
    )

    assert is_real_agent_team_execution_enabled(settings, service=service) is True


def test_requested_real_execution_fails_closed_without_runtime_instead_of_falling_back(
    tmp_path: Path,
) -> None:
    service, _, _ = _service(tmp_path)
    task = _task(service)
    del service._agent_team_runtime

    result = execute_task_body(service, task, user_id="user-1")

    assert result.final_status == AgentTeamTaskStatus.BLOCKED
    assert result.run_status == "blocked"
    assert result.execution_status == "readiness_blocked"
    assert "runtime readiness" in result.last_error
    assert service.repository.list_task_runs(task_id=task.task_id) == []


@pytest.mark.parametrize(
    "configure_not_ready",
    [
        lambda settings: setattr(settings, "agent_team_durable_required", False),
        lambda settings: settings.resolved_env.__setitem__("FOCUS_AGENT_SANDBOX_BACKEND", "auto"),
    ],
)
def test_requested_real_execution_never_falls_back_when_readiness_is_not_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    configure_not_ready: Any,
) -> None:
    service, _, _ = _service(tmp_path)
    task = _task(service)
    configure_not_ready(service.settings)

    def legacy_execution_must_not_run(**_: Any) -> None:
        raise AssertionError("legacy delegated execution must not run")

    monkeypatch.setattr(run_execution_module, "run_delegated_tasks", legacy_execution_must_not_run)

    result = execute_task_body(service, task, user_id="user-1")

    assert result.final_status == AgentTeamTaskStatus.BLOCKED
    assert result.run_status == "blocked"
    assert result.execution_status == "readiness_blocked"
    assert "runtime readiness" in result.last_error
    assert service.repository.list_task_runs(task_id=task.task_id) == []


def test_scoped_tool_handlers_bind_their_own_tool_name_and_instance() -> None:
    read_tool = RecordingTool("read_file")
    search_tool = RecordingTool("search_code")

    scoped_tools = _task_scoped_tools(
        {"read_file": read_tool, "search_code": search_tool},
        ["read_file", "search_code"],
    )

    assert [tool.handler({"path": tool.name}) for tool in scoped_tools] == [
        "read_file",
        "search_code",
    ]
    assert read_tool.calls == [{"path": "read_file"}]
    assert search_tool.calls == [{"path": "search_code"}]


def test_scoped_command_uses_injected_docker_only_copy_discard_sandbox(tmp_path: Path) -> None:
    sandbox_runner = CountingSandboxRunner()
    tools = build_agent_team_scoped_tools(
        workspace_root=tmp_path,
        sandbox_runner=sandbox_runner,
        task_id="task-sandbox",
        require_docker=True,
        allow_fallback=False,
    )

    payload = json.loads(tools["run_workspace_command"].invoke({"command": ["pytest", "-q"]}))

    assert payload["ok"] is True
    assert payload["evidence"] == {
        "kind": "agent_team_sandbox_command",
        "task_id": "task-sandbox",
        "workspace_root": str(tmp_path.resolve()),
        "sandbox_backend": "docker",
        "sandbox_id": None,
        "run_id": None,
        "exit_code": 0,
        "timed_out": False,
        "fallback_used": False,
        "fallback_reason": None,
        "require_docker": True,
        "allow_fallback": False,
        "policy_violations": [],
    }
    request = sandbox_runner.requests[0]
    assert request.workspace_root == tmp_path.resolve()
    assert request.workspace_mode == "copy_discard"
    assert request.fallback_policy == "deny"
    assert request.allow_network is False
    assert request.policy == {
        "agent_team_task_id": "task-sandbox",
        "require_docker": True,
        "allow_fallback": False,
    }


def test_real_execution_adapts_bound_langchain_model_without_touching_chat_runtime(
    tmp_path: Path,
) -> None:
    service, _, _ = _service(tmp_path)
    task = _task(service)
    model = FakeLangChainModel()
    service.task_agent_model_factory = lambda **_: model

    outcome = execute_real_agent_team_task(
        service,
        task=task,
        user_id="user-1",
        workspace_metadata=_workspace_metadata(
            task, Path(service.workspace_service.workspace_path)
        ),
        scheduler_wave=1,
    )

    task_run = service.repository.get_task_run(outcome.task_updates["task_run_id"])
    assert outcome.final_status == AgentTeamTaskStatus.DONE
    assert task_run.status == AgentTeamTaskStatus.DONE
    assert model.bound_tool_names == ["read_file", "search_code"]
    assert model.messages[0].type == "human"
    assert (
        service.repository.list_task_run_events(task_run_id=task_run.task_run_id)[-1].status
        == "done"
    )


def test_real_execution_setup_failure_finalizes_persisted_task_run(tmp_path: Path) -> None:
    service, _, _ = _service(tmp_path)
    task = _task(service)

    def broken_model_factory(**_: Any) -> Any:
        raise TypeError("configured provider is unavailable")

    service.task_agent_model_factory = broken_model_factory
    outcome = execute_real_agent_team_task(
        service,
        task=task,
        user_id="user-1",
        workspace_metadata=_workspace_metadata(
            task, Path(service.workspace_service.workspace_path)
        ),
        scheduler_wave=1,
    )

    task_run = service.repository.get_task_run(outcome.task_updates["task_run_id"])
    events = service.repository.list_task_run_events(task_run_id=task_run.task_run_id)
    evidence = service.repository.list_evidence_records(task_run_id=task_run.task_run_id)

    assert outcome.final_status == AgentTeamTaskStatus.FAILED
    assert task_run.status == AgentTeamTaskStatus.FAILED
    assert task_run.finished_at
    assert task_run.last_error == outcome.error
    assert [event.event_type for event in events] == ["started", "failed"]
    assert evidence[-1].source_type == "execution_failure"
    assert evidence[-1].evidence_verdict == AgentTeamEvidenceVerdict.REJECTED


def test_real_execution_readiness_rejects_missing_durable_docker_or_fencing(
    tmp_path: Path,
) -> None:
    service, _, _ = _service(tmp_path)

    service.settings.agent_team_durable_required = False
    assert is_real_agent_team_execution_enabled(service.settings, service=service) is False

    service.settings = _real_settings(Path(service.workspace_service.workspace_path))
    service.settings.resolved_env["FOCUS_AGENT_SANDBOX_BACKEND"] = "auto"
    assert is_real_agent_team_execution_enabled(service.settings, service=service) is False

    service.settings = _real_settings(Path(service.workspace_service.workspace_path))
    service.settings.agent_team_fencing_enabled = False
    assert is_real_agent_team_execution_enabled(service.settings, service=service) is False


def test_scoped_tool_setup_failure_finalizes_persisted_task_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _, _ = _service(tmp_path)
    task = _task(service)

    def broken_scoped_tools(**_: Any) -> dict[str, Any]:
        raise RuntimeError("scoped tools could not be initialized")

    monkeypatch.setattr(
        real_execution_module,
        "build_agent_team_scoped_tools",
        broken_scoped_tools,
    )
    outcome = execute_real_agent_team_task(
        service,
        task=task,
        user_id="user-1",
        workspace_metadata=_workspace_metadata(
            task, Path(service.workspace_service.workspace_path)
        ),
        scheduler_wave=1,
    )

    task_run = service.repository.get_task_run(outcome.task_updates["task_run_id"])
    events = service.repository.list_task_run_events(task_run_id=task_run.task_run_id)

    assert outcome.final_status == AgentTeamTaskStatus.FAILED
    assert task_run.status == AgentTeamTaskStatus.FAILED
    assert task_run.metadata["failure_stage"] == "setup"
    assert [event.event_type for event in events] == ["started", "failed"]


def test_real_execution_queues_redacted_approval_and_never_auto_resumes(tmp_path: Path) -> None:
    service, queue, sandbox_runner = _service(tmp_path)
    task = _task(service, write_scope=["src/**"])
    model = SequencedTaskModel(
        [
            TaskModelResponse(
                tool_calls=(
                    TaskToolCall(
                        call_id="patch-1",
                        name="apply_patch",
                        arguments={
                            "patch": "secret patch contents",
                            "api_token": "secret-token",
                        },
                    ),
                )
            )
        ]
    )
    service.task_agent_model_factory = lambda **_: model
    service.update_task(
        task_id=task.task_id,
        user_id="user-1",
        status=AgentTeamTaskStatus.QUEUED,
        run_status="queued",
        execution_status="queued",
    )

    blocked = service.run_task_claimed(task_id=task.task_id, user_id="user-1")
    task_run = service.repository.get_task_run(blocked.task_run_id or "")
    pending = queue.get(task_run.metadata["approval"]["request_id"])

    assert blocked.status == AgentTeamTaskStatus.BLOCKED
    assert blocked.execution_status == "awaiting_approval"
    assert pending is not None
    assert pending.tool_name == "apply_patch"
    assert pending.tool_args == {"patch": "[REDACTED]", "api_token": "[REDACTED]"}
    assert task_run.status == AgentTeamTaskStatus.BLOCKED
    assert task_run.metadata["approval"]["resume_supported"] is False
    assert "automatic" in task_run.metadata["approval"]["resume_reason"]
    checkpoints = service.repository.list_task_checkpoints(task_run_id=task_run.task_run_id)
    tool_executions = service.repository.list_tool_executions(task_run_id=task_run.task_run_id)
    assert "secret patch contents" not in repr(checkpoints)
    assert "secret-token" not in repr(checkpoints)
    assert "secret patch contents" not in repr(tool_executions)
    assert "secret-token" not in repr(tool_executions)
    assert sandbox_runner.requests == []
    assert model.calls == 1

    queue.decide(request_id=pending.request_id, approved=True, decided_by="reviewer")

    assert service.get_task(task.task_id, user_id="user-1").status == AgentTeamTaskStatus.BLOCKED
    assert sandbox_runner.requests == []
    assert model.calls == 1
    assert queue.get(pending.request_id).status.value == "approved"


def test_read_only_verifier_with_clean_workspace_and_docker_evidence_passes_strong_gate(
    tmp_path: Path,
) -> None:
    service, _, _ = _service(tmp_path)
    task = _task(service, role=AgentTeamTaskRole.VERIFIER)
    workspace_path = Path(service.workspace_service.workspace_path)
    run = _running_task_run(task)
    service.repository.create_task_run(run)
    result = TaskRunResult(
        run_id=run.task_run_id,
        scope=TaskExecutionScope(
            task_id=task.task_id,
            session_id=task.session_id,
            user_id="user-1",
            workspace_path=str(workspace_path),
            allowed_tool_names=frozenset({"run_workspace_command"}),
        ),
        status=TaskRunStatus.COMPLETED,
        rounds_completed=1,
        final_answer="pytest passed in the clean verifier worktree.",
        messages=(),
        checkpoints=(),
        evidence=(
            TaskExecutionEvidence(
                run_id=run.task_run_id,
                task_id=task.task_id,
                round_number=1,
                kind="tool_result",
                tool_call_id="command-1",
                tool_name="run_workspace_command",
                value={
                    "status": "completed",
                    "output": json.dumps(
                        {
                            "command": ["pytest", "-q"],
                            "evidence": {
                                "exit_code": 0,
                                "sandbox_backend": "docker",
                                "fallback_used": False,
                                "sandbox_id": "docker-test",
                                "run_id": "sandbox-run-1",
                                "timed_out": False,
                            },
                        }
                    ),
                },
            ),
        ),
    )

    outcome = _outcome_from_result(
        service,
        task=task,
        run=run,
        result=result,
        workspace_metadata=_workspace_metadata(task, workspace_path),
        scheduler_wave=1,
    )
    assert outcome.output is not None
    evidence = outcome.output["metadata"]["evidence"]
    assert evidence["changed_files"] == []
    assert evidence["worktree_hash"]
    assert evidence["diff_hash"]
    assert evidence["worktree_hash"] != evidence["diff_hash"]

    service.record_task_output(task_id=task.task_id, user_id="user-1", **outcome.output)
    service.update_task(
        task_id=task.task_id,
        user_id="user-1",
        status=outcome.final_status,
        run_status=outcome.run_status,
        execution_status=outcome.execution_status,
        last_error=outcome.error,
        **outcome.task_updates,
    )
    bundle = service.prepare_merge_bundle(session_id=task.session_id, user_id="user-1")

    assert bundle.recommended_next_action.value == "merge"
    assert not any("diff hash evidence is required" in item for item in bundle.risk_items)


def test_strong_gate_rejects_verified_command_without_workspace_capture(tmp_path: Path) -> None:
    service, _, _ = _service(tmp_path)
    task = _task(service, role=AgentTeamTaskRole.VERIFIER)
    service.record_task_output(
        task_id=task.task_id,
        user_id="user-1",
        kind="test_report",
        summary="The Docker test command passed but workspace status was unavailable.",
        test_evidence=["pytest -q"],
        metadata={
            "evidence": {
                "execution_class": "sandbox_verified",
                "evidence_level": "verified",
                "evidence_verdict": "verified",
                "sandbox_backend": "docker",
                "fallback_used": False,
                "commands": [{"command": "pytest -q", "exit_code": 0}],
            }
        },
    )
    service.update_task(
        task_id=task.task_id,
        user_id="user-1",
        status=AgentTeamTaskStatus.DONE,
        run_status="completed",
        execution_status="completed",
    )

    bundle = service.prepare_merge_bundle(session_id=task.session_id, user_id="user-1")

    assert bundle.recommended_next_action.value == "request_changes"
    assert any("worktree hash evidence is required" in item for item in bundle.risk_items)
    assert any("diff hash evidence is required" in item for item in bundle.risk_items)


def test_workspace_capture_failure_finalizes_task_run_without_hashes(tmp_path: Path) -> None:
    service, _, _ = _service(tmp_path, status_error=RuntimeError("git status failed"))
    task = _task(service)
    service.task_agent_model_factory = lambda **_: SequencedTaskModel(
        [TaskModelResponse(content="The task completed.")]
    )

    outcome = execute_real_agent_team_task(
        service,
        task=task,
        user_id="user-1",
        workspace_metadata=_workspace_metadata(
            task, Path(service.workspace_service.workspace_path)
        ),
        scheduler_wave=1,
    )

    task_run = service.repository.get_task_run(outcome.task_updates["task_run_id"])
    evidence = service.repository.list_evidence_records(task_run_id=task_run.task_run_id)

    assert outcome.final_status == AgentTeamTaskStatus.FAILED
    assert task_run.status == AgentTeamTaskStatus.FAILED
    assert "workspace_evidence" not in task_run.metadata
    assert "worktree_hash" not in task_run.metadata
    assert "diff_hash" not in task_run.metadata
    assert evidence[-1].source_type == "execution_failure"
