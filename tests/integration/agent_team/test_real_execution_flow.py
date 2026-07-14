"""End-to-end evidence for the guarded Agent Team real-execution projection.

The suite uses a real temporary git repository and the public ``run_task``
entrypoint. Docker and the task model are deterministic test doubles, but the
service still creates a real worktree, runs the production task loop, persists
runtime records, projects task/output provenance, and invokes the merge gate.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from focus_agent.capabilities.sandbox_execution import (
    SandboxExecutionRequest,
    SandboxExecutionResult,
)
from focus_agent.config import ConfiguredModel, ModelCatalogConfig, ProviderConfig, Settings
from focus_agent.core.agent_team import (
    AgentTeamEvidenceLevel,
    AgentTeamEvidenceVerdict,
    AgentTeamExecutionClass,
    AgentTeamRecommendedAction,
    AgentTeamTaskRole,
    AgentTeamTaskStatus,
)
from focus_agent.services.agent_team import AgentTeamService
from focus_agent.services.agent_team_execution_runtime import (
    TaskAgentMessage,
    TaskAgentRunner,
    TaskExecutionScope,
    TaskModelResponse,
    TaskToolCall,
)
from focus_agent.services.agent_team_workspace import AgentTeamWorkspaceService


def _git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _temporary_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init")
    _git(repository, "config", "user.name", "Agent Team Integration")
    _git(repository, "config", "user.email", "agent-team-integration@example.test")
    (repository / "README.md").write_text("baseline\n", encoding="utf-8")
    _git(repository, "add", "README.md")
    _git(repository, "commit", "-m", "fixture baseline")
    return repository


def _real_execution_settings(repository_root: Path) -> Settings:
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
        agent_delegation_execution_mode="inline",
        agent_team_real_provider_enabled=True,
        agent_team_durable_required=True,
        agent_team_fencing_enabled=True,
        agent_team_cross_session_locks_enabled=True,
        agent_team_kill_switch_enabled=False,
        background_job_backend="postgres",
        background_job_execution="durable",
        database_uri="postgresql://integration:ignored@example.test/focus_agent",
        workspace_root=str(repository_root),
        resolved_env={
            "OPENAI_API_KEY": "integration-only-reference",
            "FOCUS_AGENT_SANDBOX_BACKEND": "docker",
            "FOCUS_AGENT_SANDBOX_ALLOW_LOCAL_FALLBACK": "0",
        },
    )


class PostgresIntegrationRepository:
    """Class-name-only readiness shim; task records remain safely in-memory."""


class PostgresIntegrationResourceLocks:
    """Class-name-only readiness shim; the task does not request resource claims."""


class _HealthyDurableWorker:
    def snapshot(self) -> dict[str, int]:
        return {
            "durable_worker_started": 1,
            "durable_worker_thread_alive": 1,
            "durable_worker_heartbeat_fresh": 1,
        }


class _DockerSandboxRunner:
    def __init__(self) -> None:
        self.requests: list[SandboxExecutionRequest] = []

    def run(self, request: SandboxExecutionRequest) -> SandboxExecutionResult:
        self.requests.append(request)
        return SandboxExecutionResult(
            status="completed",
            command=list(request.command),
            cwd=request.cwd,
            exit_code=0,
            timed_out=False,
            timeout_seconds=request.timeout_seconds,
            stdout="1 passed\n",
            stderr="",
            stdout_truncated=False,
            stderr_truncated=False,
            outputs=[],
            outputs_truncated=False,
            duration_ms=1.0,
            sandbox_backend="docker",
            run_id=f"sandbox-run-{len(self.requests)}",
            policy=dict(request.policy),
            sandbox_id=request.sandbox_id,
            fallback_used=False,
            workspace_mode=request.workspace_mode,
        )


class _RunCommandThenFinishModel:
    def __init__(self) -> None:
        self._calls = 0

    def invoke(
        self,
        messages: tuple[TaskAgentMessage, ...],
        *,
        tools: tuple[Any, ...],
        scope: TaskExecutionScope,
        cancellation_token: Any,
    ) -> TaskModelResponse:
        del messages, tools, scope, cancellation_token
        self._calls += 1
        if self._calls == 1:
            return TaskModelResponse(
                content="I will run the requested verification.",
                tool_calls=(
                    TaskToolCall(
                        call_id="verify-worktree",
                        name="run_workspace_command",
                        arguments={
                            "command": [
                                "pytest",
                                "-q",
                                "tests/integration/agent_team/test_real_execution_flow.py",
                            ]
                        },
                    ),
                ),
            )
        return TaskModelResponse(content="Docker verification completed in the task worktree.")


def _approved_runner_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    from focus_agent.services import agent_team_real_execution

    production_runner = TaskAgentRunner

    def create_runner(**kwargs: Any) -> TaskAgentRunner:
        return production_runner(**kwargs, approval_decider=lambda _request: True)

    monkeypatch.setattr(agent_team_real_execution, "TaskAgentRunner", create_runner)


def _service(
    *,
    repository_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[AgentTeamService, _DockerSandboxRunner]:
    service = AgentTeamService(
        branch_service=None,
        settings=_real_execution_settings(repository_root),
        workspace_service=AgentTeamWorkspaceService(repo_root=repository_root),
    )
    service._agent_team_runtime = SimpleNamespace(
        agent_team_service=SimpleNamespace(repository=PostgresIntegrationRepository()),
        durable_background_worker=_HealthyDurableWorker(),
        coordination_backend=SimpleNamespace(
            resource_locks=PostgresIntegrationResourceLocks(),
            approval_queue=object(),
        ),
    )
    sandbox_runner = _DockerSandboxRunner()
    service.agent_team_sandbox_runner = sandbox_runner
    service.task_agent_model_factory = lambda **_kwargs: _RunCommandThenFinishModel()
    service._enqueue_durable_job = lambda **_kwargs: False
    _approved_runner_factory(monkeypatch)
    return service, sandbox_runner


@pytest.mark.skipif(
    shutil.which("git") is None,
    reason="git executable is required for real worktree execution evidence",
)
def test_public_run_task_projects_real_worktree_sandbox_evidence_and_merge_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root = _temporary_repository(tmp_path)
    service, sandbox_runner = _service(
        repository_root=repository_root,
        monkeypatch=monkeypatch,
    )
    session = service.create_session(
        user_id="user-1",
        goal="Validate real worktree sandbox evidence projection.",
    )
    task = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal="Run the task-scoped verification command.",
        scope=["run_workspace_command"],
        write_scope=["README.md"],
        evidence_required=["pytest"],
        create_branch=False,
    )

    completed = service.run_task(task_id=task.task_id, user_id="user-1")

    assert completed.status == AgentTeamTaskStatus.DONE
    assert completed.run_status == "completed"
    assert completed.execution_status == "completed"
    assert completed.workspace_path is not None
    assert Path(completed.workspace_path).is_dir()
    assert completed.workspace_path != str(repository_root)
    assert completed.workspace_branch
    assert completed.base_commit == _git(repository_root, "rev-parse", "HEAD").strip()
    assert completed.task_run_id
    assert completed.sandbox_id
    assert completed.execution_profile == "worktree_sandbox"
    assert completed.execution_class == AgentTeamExecutionClass.SANDBOX_VERIFIED
    assert completed.evidence_level == AgentTeamEvidenceLevel.VERIFIED
    assert completed.evidence_verdict == AgentTeamEvidenceVerdict.VERIFIED
    assert completed.deliverable is True

    assert len(sandbox_runner.requests) == 1
    request = sandbox_runner.requests[0]
    assert request.workspace_root == Path(completed.workspace_path)
    assert request.workspace_mode == "copy_discard"
    assert request.fallback_policy == "deny"
    assert request.policy["require_docker"] is True
    assert request.policy["allow_fallback"] is False

    runs = service.repository.list_task_runs(task_id=task.task_id)
    assert len(runs) == 1
    run = runs[0]
    assert run.task_run_id == completed.task_run_id
    assert run.status == AgentTeamTaskStatus.DONE
    assert run.execution_class == AgentTeamExecutionClass.SANDBOX_VERIFIED
    assert run.deliverable is True
    assert run.metadata["workspace_evidence"]["workspace_path"] == completed.workspace_path
    assert run.metadata["workspace_evidence"]["worktree_hash"]
    assert run.metadata["workspace_evidence"]["diff_hash"]
    assert run.metadata["command_evidence"] == [
        {
            "command": [
                "pytest",
                "-q",
                "tests/integration/agent_team/test_real_execution_flow.py",
            ],
            "exit_code": 0,
            "sandbox_backend": "docker",
            "fallback_used": False,
            "sandbox_id": request.sandbox_id,
            "run_id": "sandbox-run-1",
            "timed_out": False,
        }
    ]

    evidence = service.repository.list_evidence_records(task_run_id=run.task_run_id)
    assert {
        (item.source_type, item.evidence_level, item.evidence_verdict) for item in evidence
    } == {
        (
            "worktree",
            AgentTeamEvidenceLevel.WORKTREE,
            AgentTeamEvidenceVerdict.INCONCLUSIVE,
        ),
        (
            "sandbox_command",
            AgentTeamEvidenceLevel.VERIFIED,
            AgentTeamEvidenceVerdict.VERIFIED,
        ),
    }
    assert service.repository.list_tool_executions(task_run_id=run.task_run_id)
    assert {
        event.event_type
        for event in service.repository.list_task_run_events(task_run_id=run.task_run_id)
    } >= {"started", "completed", "tool_start", "tool_end"}

    outputs = service.list_task_outputs(task_id=task.task_id, user_id="user-1")
    assert len(outputs) == 1
    output = outputs[0]
    assert output.task_run_id == run.task_run_id
    assert output.sandbox_id == run.sandbox_id
    assert output.execution_class == AgentTeamExecutionClass.SANDBOX_VERIFIED
    assert output.evidence_level == AgentTeamEvidenceLevel.VERIFIED
    assert output.evidence_verdict == AgentTeamEvidenceVerdict.VERIFIED
    assert output.deliverable is True
    assert (
        output.metadata["evidence"]["worktree_hash"]
        == run.metadata["workspace_evidence"]["worktree_hash"]
    )
    assert (
        output.metadata["evidence"]["diff_hash"] == run.metadata["workspace_evidence"]["diff_hash"]
    )
    assert output.metadata["evidence"]["commands"][0]["sandbox_backend"] == "docker"
    assert output.metadata["evidence"]["commands"][0]["fallback_used"] is False
    assert output.metadata["evidence"]["commands"][0]["exit_code"] == 0

    bundle = service.prepare_merge_bundle(session_id=session.session_id, user_id="user-1")
    assert bundle.recommended_next_action == AgentTeamRecommendedAction.MERGE
    assert not any("Strong evidence gate rejected" in item for item in bundle.risk_items)


@pytest.mark.skipif(
    shutil.which("git") is None,
    reason="git executable is required for real worktree execution evidence",
)
def test_real_execution_setup_failure_finishes_claimed_task_instead_of_leaving_it_running(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root = _temporary_repository(tmp_path)
    service, _ = _service(repository_root=repository_root, monkeypatch=monkeypatch)
    session = service.create_session(
        user_id="user-1",
        goal="Ensure real setup failures leave a terminal task state.",
    )
    task = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal="Trigger deterministic real-execution setup failure.",
        scope=["run_workspace_command"],
        write_scope=["README.md"],
        create_branch=False,
    )
    service.agent_team_sandbox_runner = None
    service.task_agent_model_factory = lambda **_kwargs: (_ for _ in ()).throw(
        RuntimeError("fake model factory setup failure")
    )

    completed = service.run_task(task_id=task.task_id, user_id="user-1")
    reloaded = service.get_task(task.task_id, user_id="user-1")

    assert completed.status == AgentTeamTaskStatus.FAILED
    assert reloaded.status == AgentTeamTaskStatus.FAILED
    assert reloaded.status != AgentTeamTaskStatus.RUNNING
    assert reloaded.run_status == "failed"
    assert reloaded.execution_status == "failed"
    assert "Real Agent Team tool-loop setup failed" in (reloaded.last_error or "")
    assert reloaded.finished_at is not None
    assert reloaded.claim_token is None

    runs = service.repository.list_task_runs(task_id=task.task_id)
    assert len(runs) == 1
    run = runs[0]
    assert run.status == AgentTeamTaskStatus.FAILED
    assert run.finished_at is not None
    assert run.metadata["failure_stage"] == "setup"
    assert run.deliverable is False
    failure_evidence = service.repository.list_evidence_records(task_run_id=run.task_run_id)
    assert [(item.source_type, item.evidence_verdict) for item in failure_evidence] == [
        ("execution_failure", AgentTeamEvidenceVerdict.REJECTED)
    ]
    assert service.list_task_outputs(task_id=task.task_id, user_id="user-1") == []
