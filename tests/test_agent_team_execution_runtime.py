from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from focus_agent.multi_agent.resource_lock import InMemoryResourceLockManager
from focus_agent.services.agent_team_execution_runtime import (
    CancellationToken,
    TaskAgentMessage,
    TaskAgentRunner,
    TaskExecutionEventType,
    TaskExecutionScope,
    TaskModelResponse,
    TaskRunCoordinator,
    TaskRunStatus,
    TaskScopedTool,
    TaskToolCall,
)
from focus_agent.services.agent_team_run_execution import acquire_task_resource_claims


class SequencedFakeModel:
    def __init__(self, responses: list[TaskModelResponse]) -> None:
        self._responses = iter(responses)
        self.calls: list[tuple[tuple[TaskAgentMessage, ...], tuple[str, ...], str | None]] = []

    def invoke(
        self,
        messages: tuple[TaskAgentMessage, ...],
        *,
        tools: tuple[Any, ...],
        scope: TaskExecutionScope,
        cancellation_token: CancellationToken,
    ) -> TaskModelResponse:
        cancellation_token.raise_if_cancelled()
        self.calls.append((messages, tuple(tool.name for tool in tools), scope.workspace_path))
        return next(self._responses)


@dataclass
class FakeTask:
    task_id: str = "task-1"
    session_id: str = "session-1"
    role: str = "backend_executor"
    goal: str = "Inspect the scoped workspace."
    scope: list[str] | None = None
    write_scope: list[str] | None = None
    workspace_path: str | None = "/tmp/focus-agent-task-1"


class _ResourceClaimService:
    def __init__(
        self,
        *,
        settings: object,
        resource_locks: InMemoryResourceLockManager,
        repo_root: str | None = "/workspace/focus-agent",
    ) -> None:
        self.settings = settings
        self.coordination_backend = SimpleNamespace(resource_locks=resource_locks)
        self.workspace_service = SimpleNamespace(repo_root=repo_root)

    def _release_task_resource_claims(self, claims: list[object]) -> None:
        for claim in claims:
            self.coordination_backend.resource_locks.release(claim)


def _resource_claim_task(
    *,
    task_id: str,
    session_id: str,
    context_refs: list[dict[str, str]] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        task_id=task_id,
        session_id=session_id,
        role=SimpleNamespace(value="backend_executor"),
        resource_claims=["file:src/focus_agent/services/shared.py"],
        context_refs=context_refs or [],
    )


def _scope(*tool_names: str) -> TaskExecutionScope:
    return TaskExecutionScope(
        task_id="task-1",
        session_id="session-1",
        user_id="user-1",
        workspace_path="/tmp/focus-agent-task-1",
        allowed_tool_names=frozenset(tool_names),
        write_scope=("src/focus_agent/services",),
    )


def test_task_resource_claims_fence_same_tenant_repository_across_sessions() -> None:
    locks = InMemoryResourceLockManager()
    settings = SimpleNamespace(
        multi_agent_v2_enabled=True,
        multi_agent_resource_lock_enabled=True,
        multi_agent_resource_lock_ttl_seconds=30.0,
        agent_team_fencing_enabled=True,
        agent_team_cross_session_locks_enabled=True,
    )
    service = _ResourceClaimService(
        settings=settings,
        resource_locks=locks,
    )
    first_task = _resource_claim_task(
        task_id="task-a",
        session_id="session-a",
        context_refs=[
            {
                "tenant_id": "tenant-a",
                "repository_id": "repo:focus-agent",
            }
        ],
    )
    second_task = _resource_claim_task(
        task_id="task-b",
        session_id="session-b",
        context_refs=[
            {
                "tenant_id": "tenant-a",
                "repository_id": "repo:focus-agent",
            }
        ],
    )

    first_claims = acquire_task_resource_claims(service, first_task)
    second_claims = acquire_task_resource_claims(service, second_task)

    assert len(first_claims) == 1
    assert first_claims[0].tenant_id == "tenant-a"
    assert first_claims[0].resource_namespace == "repo:focus-agent"
    assert first_claims[0].fence_token == 1
    assert second_claims == []


def test_task_resource_claims_use_conservative_tenant_when_metadata_is_unavailable() -> None:
    locks = InMemoryResourceLockManager()
    settings = SimpleNamespace(
        multi_agent_v2_enabled=True,
        multi_agent_resource_lock_enabled=True,
        multi_agent_resource_lock_ttl_seconds=30.0,
        agent_team_fencing_enabled=True,
        agent_team_cross_session_locks_enabled=True,
    )
    service = _ResourceClaimService(
        settings=settings,
        resource_locks=locks,
    )

    first_claims = acquire_task_resource_claims(
        service,
        _resource_claim_task(task_id="task-a", session_id="session-a"),
    )
    second_claims = acquire_task_resource_claims(
        service,
        _resource_claim_task(task_id="task-b", session_id="session-b"),
    )

    assert len(first_claims) == 1
    assert first_claims[0].tenant_id == "tenant:default"
    assert first_claims[0].resource_namespace == "repo:/workspace/focus-agent"
    assert first_claims[0].fence_token == 1
    assert second_claims == []


def test_task_resource_claims_do_not_conflict_across_repository_namespaces() -> None:
    locks = InMemoryResourceLockManager()
    settings = SimpleNamespace(
        multi_agent_v2_enabled=True,
        multi_agent_resource_lock_enabled=True,
        multi_agent_resource_lock_ttl_seconds=30.0,
        agent_team_fencing_enabled=True,
        agent_team_cross_session_locks_enabled=True,
    )
    service = _ResourceClaimService(settings=settings, resource_locks=locks)
    first_claims = acquire_task_resource_claims(
        service,
        _resource_claim_task(
            task_id="task-a",
            session_id="session-a",
            context_refs=[{"tenant_id": "tenant-a", "repository_id": "repo:a"}],
        ),
    )
    second_claims = acquire_task_resource_claims(
        service,
        _resource_claim_task(
            task_id="task-b",
            session_id="session-b",
            context_refs=[{"tenant_id": "tenant-a", "repository_id": "repo:b"}],
        ),
    )

    assert len(first_claims) == 1
    assert len(second_claims) == 1


def test_task_resource_claims_without_repository_metadata_are_session_namespaced() -> None:
    locks = InMemoryResourceLockManager()
    settings = SimpleNamespace(
        multi_agent_v2_enabled=True,
        multi_agent_resource_lock_enabled=True,
        multi_agent_resource_lock_ttl_seconds=30.0,
        agent_team_fencing_enabled=True,
        agent_team_cross_session_locks_enabled=True,
    )
    service = _ResourceClaimService(settings=settings, resource_locks=locks, repo_root=None)

    first_claims = acquire_task_resource_claims(
        service,
        _resource_claim_task(task_id="task-a", session_id="session-a"),
    )
    second_claims = acquire_task_resource_claims(
        service,
        _resource_claim_task(task_id="task-b", session_id="session-b"),
    )

    assert first_claims[0].resource_namespace == "session:session-a"
    assert len(second_claims) == 1


def test_task_resource_claims_remain_session_scoped_without_cross_session_flags() -> None:
    locks = InMemoryResourceLockManager()
    settings = SimpleNamespace(
        multi_agent_v2_enabled=True,
        multi_agent_resource_lock_enabled=True,
        multi_agent_resource_lock_ttl_seconds=30.0,
        agent_team_fencing_enabled=False,
        agent_team_cross_session_locks_enabled=False,
    )
    service = _ResourceClaimService(
        settings=settings,
        resource_locks=locks,
    )
    first_task = _resource_claim_task(task_id="task-a", session_id="session-a")
    second_task = _resource_claim_task(task_id="task-b", session_id="session-b")

    first_claims = acquire_task_resource_claims(service, first_task)
    second_claims = acquire_task_resource_claims(service, second_task)

    assert len(first_claims) == 1
    assert first_claims[0].is_cross_session is False
    assert first_claims[0].fence_token is None
    assert len(second_claims) == 1


def test_runner_completes_real_multi_round_tool_loop_with_scoped_tool_and_evidence() -> None:
    model = SequencedFakeModel(
        [
            TaskModelResponse(
                content="I will inspect the task workspace.",
                tool_calls=(
                    TaskToolCall(
                        call_id="read-1",
                        name="read_scoped_file",
                        arguments={"path": "src/focus_agent/services/agent_team.py"},
                    ),
                ),
            ),
            TaskModelResponse(content="The scoped file contains the required task wiring."),
        ]
    )
    tool_calls: list[tuple[dict[str, Any], TaskExecutionScope, CancellationToken]] = []
    checkpoints = []
    evidence = []

    def read_scoped_file(
        arguments: dict[str, Any],
        scope: TaskExecutionScope,
        cancellation_token: CancellationToken,
    ) -> dict[str, str]:
        tool_calls.append((arguments, scope, cancellation_token))
        assert scope.workspace_path == "/tmp/focus-agent-task-1"
        assert scope.write_scope == ("src/focus_agent/services",)
        return {"path": arguments["path"], "content": "task wiring"}

    runner = TaskAgentRunner(
        model=model,
        tools=[TaskScopedTool(name="read_scoped_file", handler=read_scoped_file)],
        checkpoint_sink=checkpoints.append,
        evidence_sink=evidence.append,
    )

    result = runner.run(scope=_scope("read_scoped_file"), prompt="Inspect the task.")

    assert result.status == TaskRunStatus.COMPLETED
    assert result.rounds_completed == 2
    assert result.final_answer == "The scoped file contains the required task wiring."
    assert [message.role for message in result.messages] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    assert tool_calls[0][0] == {"path": "src/focus_agent/services/agent_team.py"}
    assert tool_calls[0][1] == result.scope
    assert tool_calls[0][2].is_cancelled is False
    assert model.calls[0][1] == ("read_scoped_file",)
    assert model.calls[0][2] == "/tmp/focus-agent-task-1"
    assert [checkpoint.event for checkpoint in result.checkpoints] == [
        TaskExecutionEventType.MODEL_RESPONSE,
        TaskExecutionEventType.TOOL_RESULT,
        TaskExecutionEventType.MODEL_RESPONSE,
        TaskExecutionEventType.COMPLETED,
    ]
    assert checkpoints == list(result.checkpoints)
    assert evidence == list(result.evidence)
    assert [item.kind for item in result.evidence] == [
        "model_response",
        "tool_result",
        "model_response",
    ]


def test_runner_stops_when_tool_cooperatively_cancels_execution() -> None:
    model = SequencedFakeModel(
        [
            TaskModelResponse(
                tool_calls=(TaskToolCall(call_id="cancel-1", name="cancel_task"),),
            ),
            TaskModelResponse(content="This response must not be requested."),
        ]
    )

    def cancel_task(
        arguments: dict[str, Any],
        scope: TaskExecutionScope,
        cancellation_token: CancellationToken,
    ) -> None:
        del arguments, scope
        cancellation_token.cancel("The user cancelled this task.")

    runner = TaskAgentRunner(
        model=model,
        tools=[TaskScopedTool(name="cancel_task", handler=cancel_task)],
    )

    result = runner.run(scope=_scope("cancel_task"), prompt="Start and cancel.")

    assert result.status == TaskRunStatus.CANCELLED
    assert result.rounds_completed == 1
    assert result.error == "The user cancelled this task."
    assert len(model.calls) == 1
    assert result.messages[-1].role == "tool"
    assert result.messages[-1].tool_status == "completed"
    assert result.checkpoints[-1].event == TaskExecutionEventType.CANCELLED
    assert result.checkpoints[-1].payload["stage"] == "after_tool"


def test_runner_pauses_before_approval_required_tool_and_redacts_sensitive_arguments() -> None:
    model = SequencedFakeModel(
        [
            TaskModelResponse(
                tool_calls=(
                    TaskToolCall(
                        call_id="write-1",
                        name="apply_scoped_change",
                        arguments={"path": "src/example.py", "token": "secret-value"},
                    ),
                ),
            )
        ]
    )
    invocations: list[object] = []

    def apply_scoped_change(*args: object, **kwargs: object) -> None:
        invocations.append((args, kwargs))

    runner = TaskAgentRunner(
        model=model,
        tools=[
            TaskScopedTool(
                name="apply_scoped_change",
                handler=apply_scoped_change,
                requires_approval=True,
                risk_level="high",
                sensitive_argument_names=frozenset({"token"}),
            )
        ],
    )

    result = runner.run(scope=_scope("apply_scoped_change"), prompt="Apply a change.")

    assert result.status == TaskRunStatus.PAUSED_FOR_APPROVAL
    assert result.rounds_completed == 1
    assert result.pending_approval is not None
    assert result.pending_approval.tool_call_id == "write-1"
    assert result.pending_approval.tool_name == "apply_scoped_change"
    assert result.pending_approval.risk_level == "high"
    assert dict(result.pending_approval.arguments) == {
        "path": "src/example.py",
        "token": "[REDACTED]",
    }
    assert invocations == []
    assert result.messages[-1].role == "assistant"
    assert result.checkpoints[-1].event == TaskExecutionEventType.AWAITING_APPROVAL
    assert result.evidence[-1].kind == "approval_request"
    assert result.evidence[-1].value["arguments"]["token"] == "[REDACTED]"


def test_runner_executes_approval_required_tool_when_injected_decider_approves() -> None:
    model = SequencedFakeModel(
        [
            TaskModelResponse(
                tool_calls=(
                    TaskToolCall(
                        call_id="approved-1",
                        name="apply_scoped_change",
                        arguments={"path": "src/example.py"},
                    ),
                ),
            ),
            TaskModelResponse(content="The approved change was applied."),
        ]
    )
    invocations: list[dict[str, Any]] = []

    def apply_scoped_change(arguments: dict[str, Any]) -> dict[str, bool]:
        invocations.append(arguments)
        return {"changed": True}

    runner = TaskAgentRunner(
        model=model,
        tools=[
            TaskScopedTool(
                name="apply_scoped_change",
                handler=apply_scoped_change,
                requires_approval=True,
            )
        ],
        approval_decider=lambda request: request.tool_call_id == "approved-1",
    )

    result = runner.run(scope=_scope("apply_scoped_change"), prompt="Apply a change.")

    assert result.status == TaskRunStatus.COMPLETED
    assert result.final_answer == "The approved change was applied."
    assert result.pending_approval is None
    assert invocations == [{"path": "src/example.py"}]
    assert TaskExecutionEventType.AWAITING_APPROVAL not in [
        checkpoint.event for checkpoint in result.checkpoints
    ]


def test_runner_reports_tool_failure_and_does_not_call_model_again() -> None:
    model = SequencedFakeModel(
        [
            TaskModelResponse(
                tool_calls=(TaskToolCall(call_id="broken-1", name="broken_tool"),),
            ),
            TaskModelResponse(content="This response must not be requested."),
        ]
    )

    def broken_tool(arguments: dict[str, Any]) -> None:
        del arguments
        raise RuntimeError("backend unavailable")

    runner = TaskAgentRunner(
        model=model,
        tools=[TaskScopedTool(name="broken_tool", handler=broken_tool)],
    )

    result = runner.run(scope=_scope("broken_tool"), prompt="Run a failing tool.")

    assert result.status == TaskRunStatus.FAILED
    assert result.rounds_completed == 1
    assert result.error == "Tool 'broken_tool' failed: backend unavailable"
    assert len(model.calls) == 1
    assert result.messages[-1].role == "tool"
    assert result.messages[-1].tool_status == "failed"
    assert result.checkpoints[-1].event == TaskExecutionEventType.FAILED
    assert result.checkpoints[-1].payload["stage"] == "tool"


def test_runner_rejects_unscoped_tool_without_executing_it() -> None:
    model = SequencedFakeModel(
        [
            TaskModelResponse(
                tool_calls=(TaskToolCall(call_id="forbidden-1", name="not_allowed"),),
            )
        ]
    )
    invoked = False

    def not_allowed(arguments: dict[str, Any]) -> None:
        nonlocal invoked
        del arguments
        invoked = True

    runner = TaskAgentRunner(
        model=model,
        tools=[TaskScopedTool(name="not_allowed", handler=not_allowed)],
    )

    result = runner.run(scope=_scope(), prompt="Try an unscoped tool.")

    assert result.status == TaskRunStatus.FAILED
    assert result.error == "Tool 'not_allowed' is not allowed in task scope."
    assert invoked is False


def test_runner_returns_max_rounds_result_for_unfinished_tool_loop() -> None:
    model = SequencedFakeModel(
        [
            TaskModelResponse(
                tool_calls=(TaskToolCall(call_id="read-1", name="lookup"),),
            ),
            TaskModelResponse(
                tool_calls=(TaskToolCall(call_id="read-2", name="lookup"),),
            ),
        ]
    )

    runner = TaskAgentRunner(
        model=model,
        tools=[TaskScopedTool(name="lookup", handler=lambda arguments: {"ok": arguments})],
        max_rounds=2,
    )

    result = runner.run(scope=_scope("lookup"), prompt="Keep looking up.")

    assert result.status == TaskRunStatus.MAX_ROUNDS_REACHED
    assert result.rounds_completed == 2
    assert result.error == "Task execution reached the maximum of 2 model rounds."
    assert result.checkpoints[-1].event == TaskExecutionEventType.MAX_ROUNDS_REACHED


def test_coordinator_builds_scope_from_task_without_mutating_process_working_directory() -> None:
    model = SequencedFakeModel([TaskModelResponse(content="Task complete.")])
    runner = TaskAgentRunner(model=model, tools=[])
    coordinator = TaskRunCoordinator(runner)
    task = SimpleNamespace(
        task_id="task-99",
        session_id="session-99",
        role="reviewer",
        goal="Review the implementation.",
        scope=["read_file"],
        write_scope=["tests"],
        workspace_path="/tmp/task-99",
    )

    result = coordinator.run_task(task, user_id="user-99")

    assert result.status == TaskRunStatus.COMPLETED
    assert result.scope.task_id == "task-99"
    assert result.scope.session_id == "session-99"
    assert result.scope.user_id == "user-99"
    assert result.scope.workspace_path == "/tmp/task-99"
    assert result.scope.allowed_tool_names == frozenset({"read_file"})
    assert result.scope.write_scope == ("tests",)
    assert result.scope.metadata["role"] == "reviewer"
    assert result.scope.metadata["goal"] == "Review the implementation."
