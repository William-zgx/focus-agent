from __future__ import annotations

import time

from langchain.messages import AIMessage, HumanMessage, ToolMessage
from langchain.tools import tool

from focus_agent.agent_execution import FakeDelegatedRunExecutor
from focus_agent.agent_execution_types import SubagentRunResult
from focus_agent.capabilities.tool_registry import ToolRegistry
from focus_agent.config import Settings
from focus_agent.core.agent_team import (
    AgentTeamFinalAnswerStatus,
    AgentTeamSessionStatus,
    AgentTeamTaskRole,
    AgentTeamTaskStatus,
)
from focus_agent.core.request_context import RequestContext
from focus_agent.engine.graph_builder import build_graph
from focus_agent.multi_agent.approval_queue import InMemoryApprovalQueue
from focus_agent.multi_agent.contracts import AgentMessageType, LockMode
from focus_agent.multi_agent.maintenance import run_multi_agent_maintenance
from focus_agent.services.agent_team import AgentTeamService


class _AlwaysFailExecutor:
    mode = "fake"

    def execute(self, task, config):  # noqa: ANN001
        return SubagentRunResult(
            run_id=f"run-{task.task_id}-failed",
            task_id=task.task_id,
            role=task.role,
            status="failed",
            summary="simulated execution failure",
            error="simulated execution failure",
            model_id=config.model_id,
            execution_mode=self.mode,
        )


class _SingleRoundToolModel:
    def __init__(self, *, tool_calls: list[dict], final_answer: str = "done") -> None:
        self.tool_calls = tool_calls
        self.final_answer = final_answer

    def bind_tools(self, _tools):  # noqa: ANN001
        return self

    def with_config(self, _config):  # noqa: ANN001
        return self

    def invoke(self, prompt_messages):  # noqa: ANN001
        if not any(isinstance(message, ToolMessage) for message in prompt_messages):
            return AIMessage(content="", tool_calls=self.tool_calls)
        return AIMessage(content=self.final_answer)


class _QueuedOnlyBackground:
    def __init__(self) -> None:
        self.submitted: list[str] = []

    def submit(self, *, key: str, **kwargs) -> bool:  # noqa: ARG002
        self.submitted.append(key)
        return True


def test_five_task_diamond_dag_executes_and_emits_progress_messages() -> None:
    service = AgentTeamService(
        branch_service=None,
        executor=FakeDelegatedRunExecutor(),
        settings=Settings(
            multi_agent_v2_enabled=True,
            multi_agent_dag_scheduler_enabled=True,
            multi_agent_message_bus_enabled=True,
            agent_role_max_parallel_runs=2,
        ),
    )
    session = service.create_session(user_id="user-1", goal="Implement diamond workflow")
    design = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.ARCHITECT,
        goal="Design architecture",
        create_branch=False,
    )
    backend = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal="Implement backend",
        dependencies=[design.task_id],
        resource_claims=["file:src/api.py"],
        create_branch=False,
    )
    frontend = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.FRONTEND_EXECUTOR,
        goal="Implement frontend",
        dependencies=[design.task_id],
        resource_claims=["file:apps/web/app.tsx"],
        create_branch=False,
    )
    verification = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.TEST_ENGINEER,
        goal="Run integration verification",
        dependencies=[backend.task_id, frontend.task_id],
        create_branch=False,
    )
    review = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.REVIEWER,
        goal="Review final result",
        dependencies=[verification.task_id],
        create_branch=False,
    )

    _, tasks = service.run_ready_tasks_once(session_id=session.session_id, user_id="user-1")

    assert {task.status for task in tasks} == {AgentTeamTaskStatus.DONE}
    assert {task.task_id for task in tasks} == {
        design.task_id,
        backend.task_id,
        frontend.task_id,
        verification.task_id,
        review.task_id,
    }
    message_bus = service.coordination_backend.message_bus
    messages = message_bus.subscribe(session_id=session.session_id, agent_id="observer").poll()
    events_by_task = {
        message.payload["task_id"]: message.payload["event"]
        for message in messages
        if message.message_type == AgentMessageType.PROGRESS
        and message.payload.get("event") == "finished"
    }
    assert set(events_by_task) == {task.task_id for task in tasks}


def test_failed_task_degrades_after_retry_and_reassign_without_stopping_session() -> None:
    service = AgentTeamService(
        branch_service=None,
        executor=_AlwaysFailExecutor(),
        settings=Settings(
            multi_agent_v2_enabled=True,
            multi_agent_failure_handler_enabled=True,
        ),
    )
    session = service.create_session(user_id="user-1", goal="Recover failed task")
    task = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal="Task that will degrade",
        create_branch=False,
    )

    _, tasks = service.run_ready_tasks_once(session_id=session.session_id, user_id="user-1")
    updated = {item.task_id: item for item in tasks}[task.task_id]
    outputs = service.list_task_outputs(task_id=task.task_id, user_id="user-1")

    assert updated.status == AgentTeamTaskStatus.DONE
    assert updated.attempt == 3
    assert outputs[-1].summary.startswith("[DEGRADED]")
    assert outputs[-1].metadata["multi_agent"]["failure_strategy"] == "degrade"


def test_conflicting_resource_claim_keeps_second_task_waiting_without_concurrent_write() -> None:
    service = AgentTeamService(
        branch_service=None,
        settings=Settings(
            multi_agent_v2_enabled=True,
            multi_agent_dag_scheduler_enabled=True,
            multi_agent_resource_lock_enabled=True,
            agent_role_max_parallel_runs=2,
        ),
    )
    session = service.create_session(user_id="user-1", goal="Protect shared file")
    first = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal="First writer",
        resource_claims=["file:src/shared.py"],
        create_branch=False,
    )
    second = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal="Second writer",
        resource_claims=["file:src/shared.py"],
        create_branch=False,
    )
    held = service.coordination_backend.resource_locks.try_acquire(
        resource_id="file:src/shared.py",
        agent_id="external:holder",
        session_id=session.session_id,
        mode=LockMode.EXCLUSIVE,
        ttl_seconds=60,
    )
    assert held is not None

    _, tasks = service.run_ready_tasks_once(session_id=session.session_id, user_id="user-1")
    updated = {item.task_id: item for item in tasks}
    contenders = [updated[first.task_id], updated[second.task_id]]

    assert all(task.status == AgentTeamTaskStatus.PENDING for task in contenders)
    assert [task.execution_status for task in contenders].count("waiting_resource_lock") == 1


def test_merge_detects_blocking_conflicting_agent_outputs() -> None:
    service = AgentTeamService(
        branch_service=None,
        settings=Settings(multi_agent_v2_enabled=True),
    )
    session = service.create_session(user_id="user-1", goal="Merge conflicted outputs")
    first = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal="Patch A",
        create_branch=False,
    )
    second = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.FRONTEND_EXECUTOR,
        goal="Patch B",
        create_branch=False,
    )
    service.update_task(task_id=first.task_id, user_id="user-1", status=AgentTeamTaskStatus.DONE)
    service.update_task(task_id=second.task_id, user_id="user-1", status=AgentTeamTaskStatus.DONE)
    service.record_task_output(
        task_id=first.task_id,
        user_id="user-1",
        summary="The shared module should use retries.",
        changed_files=["src/shared.py"],
    )
    service.record_task_output(
        task_id=second.task_id,
        user_id="user-1",
        summary="The shared module should not use retries.",
        changed_files=["src/shared.py"],
    )

    bundle = service.prepare_merge_bundle(session_id=session.session_id, user_id="user-1")

    assert bundle.final_answer_status == AgentTeamFinalAnswerStatus.BLOCKED
    assert bundle.recommended_next_action == "request_changes"
    assert any("Merge conflict blocking" in item for item in bundle.risk_items)


def test_async_approval_pending_does_not_block_other_tool_calls(monkeypatch) -> None:
    calls: list[str] = []

    @tool
    def approval_lookup(name: str) -> str:
        """Lookup that requires approval."""
        calls.append(f"approval:{name}")
        return f"approved:{name}"

    @tool
    def safe_lookup(name: str) -> str:
        """Lookup that does not require approval."""
        calls.append(f"safe:{name}")
        return f"safe:{name}"

    approval_lookup.metadata = {
        "parallel_safe": True,
        "cacheable": False,
        "requires_approval": True,
        "risk_level": "high",
        "intent_policies": ("execution",),
        "allowed_roles": ("executor",),
    }
    safe_lookup.metadata = {
        "parallel_safe": True,
        "cacheable": False,
        "requires_approval": False,
        "risk_level": "low",
        "intent_policies": ("execution",),
        "allowed_roles": ("executor",),
    }
    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: _SingleRoundToolModel(
            tool_calls=[
                {"id": "approval-async", "name": "approval_lookup", "args": {"name": "focus"}},
                {"id": "safe-async", "name": "safe_lookup", "args": {"name": "focus"}},
            ],
            final_answer="approval queued and safe completed",
        ),
    )
    approval_queue = InMemoryApprovalQueue()
    graph = build_graph(
        settings=Settings(
            multi_agent_v2_enabled=True,
            multi_agent_async_approval_enabled=True,
            agent_tool_router_enabled=True,
            agent_tool_router_enforce=True,
        ),
        tool_registry=ToolRegistry(tools=(approval_lookup, safe_lookup)),
        approval_queue=approval_queue,
    )

    result = graph.invoke(
        {
            "messages": [HumanMessage(content="run both lookups")],
            "selected_model": "openai:deepseek-reasoner",
        },
        context=RequestContext(user_id="user-1", root_thread_id="thread-async-approval-mixed"),
        version="v2",
    )

    tool_messages = [
        message for message in result.value["messages"] if isinstance(message, ToolMessage)
    ]
    assert calls == ["safe:focus"]
    assert approval_queue.list_pending()[-1].tool_name == "approval_lookup"
    assert [message.tool_call_id for message in tool_messages] == [
        "approval-async",
        "safe-async",
    ]
    assert tool_messages[0].artifact["runtime"]["tool_approval_pending"] is True
    assert tool_messages[1].content == "safe:focus"


def test_dag_scheduler_queues_only_one_same_resource_task_in_a_wave() -> None:
    background = _QueuedOnlyBackground()
    service = AgentTeamService(
        branch_service=None,
        settings=Settings(
            multi_agent_v2_enabled=True,
            multi_agent_dag_scheduler_enabled=True,
            agent_role_max_parallel_runs=2,
        ),
        background_work=background,
    )
    session = service.create_session(user_id="user-1", goal="Schedule same resource tasks")
    first = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal="Patch shared module A",
        resource_claims=["file:src/shared.py"],
        create_branch=False,
    )
    second = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal="Patch shared module B",
        resource_claims=["file:src/shared.py"],
        create_branch=False,
    )

    _, tasks = service.run_ready_tasks_once(session_id=session.session_id, user_id="user-1")
    statuses = {task.task_id: task.status for task in tasks}

    assert sorted(statuses.values()) == [
        AgentTeamTaskStatus.PENDING,
        AgentTeamTaskStatus.QUEUED,
    ]
    assert {first.task_id, second.task_id} == set(statuses)
    assert len(background.submitted) == 1


def test_legacy_scheduler_flag_off_keeps_existing_parallel_queue_behavior() -> None:
    background = _QueuedOnlyBackground()
    service = AgentTeamService(
        branch_service=None,
        settings=Settings(
            multi_agent_v2_enabled=False,
            agent_role_max_parallel_runs=2,
        ),
        background_work=background,
    )
    session = service.create_session(user_id="user-1", goal="Legacy scheduling")
    first = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal="Legacy task A",
        resource_claims=["file:src/shared.py"],
        create_branch=False,
    )
    second = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal="Legacy task B",
        resource_claims=["file:src/shared.py"],
        create_branch=False,
    )

    _, tasks = service.run_ready_tasks_once(session_id=session.session_id, user_id="user-1")
    statuses = {task.task_id: task.status for task in tasks}

    assert statuses == {
        first.task_id: AgentTeamTaskStatus.QUEUED,
        second.task_id: AgentTeamTaskStatus.QUEUED,
    }
    assert len(background.submitted) == 2


def test_dag_scheduler_keeps_child_pending_until_dependency_done() -> None:
    background = _QueuedOnlyBackground()
    service = AgentTeamService(
        branch_service=None,
        settings=Settings(
            multi_agent_v2_enabled=True,
            multi_agent_dag_scheduler_enabled=True,
            agent_role_max_parallel_runs=2,
        ),
        background_work=background,
    )
    session = service.create_session(user_id="user-1", goal="Dependency ordering")
    parent = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.ARCHITECT,
        goal="Design first",
        create_branch=False,
    )
    child = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal="Implement after design",
        dependencies=[parent.task_id],
        create_branch=False,
    )

    _, tasks = service.run_ready_tasks_once(session_id=session.session_id, user_id="user-1")
    statuses = {task.task_id: task.status for task in tasks}

    assert statuses[parent.task_id] == AgentTeamTaskStatus.QUEUED
    assert statuses[child.task_id] == AgentTeamTaskStatus.PENDING
    assert len(background.submitted) == 1


def test_dag_scheduler_blocks_invalid_graph_instead_of_silent_stall() -> None:
    background = _QueuedOnlyBackground()
    service = AgentTeamService(
        branch_service=None,
        settings=Settings(
            multi_agent_v2_enabled=True,
            multi_agent_dag_scheduler_enabled=True,
            agent_role_max_parallel_runs=2,
        ),
        background_work=background,
    )
    session = service.create_session(user_id="user-1", goal="Invalid DAG")
    task = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal="Task with missing parent",
        dependencies=["missing-task-id"],
        create_branch=False,
    )

    _, tasks = service.run_ready_tasks_once(session_id=session.session_id, user_id="user-1")
    updated = {item.task_id: item for item in tasks}[task.task_id]

    assert updated.status == AgentTeamTaskStatus.BLOCKED
    assert updated.run_status == "blocked"
    assert updated.execution_status == "scheduler_blocked"
    assert "depends on unknown task" in (updated.last_error or "")
    assert service.get_session(session.session_id, user_id="user-1").status == (
        AgentTeamSessionStatus.FAILED
    )
    assert background.submitted == []


def test_maintenance_tick_cleans_expired_runtime_state() -> None:
    service = AgentTeamService(
        branch_service=None,
        settings=Settings(multi_agent_v2_enabled=True),
    )
    session = service.create_session(user_id="user-1", goal="Maintenance")
    backend = service.coordination_backend
    backend.message_bus.default_ttl_seconds = 0.001
    backend.resource_locks.try_acquire(
        resource_id="file:src/stale.py",
        agent_id="executor:stale",
        session_id=session.session_id,
        mode=LockMode.EXCLUSIVE,
        ttl_seconds=0.001,
    )
    backend.message_bus.publish(
        session_id=session.session_id,
        source_agent="executor:stale",
        target_agent=None,
        message_type=AgentMessageType.PROGRESS,
        payload={"event": "stale"},
    )
    backend.approval_queue.submit_pending(
        request_id="approval-stale",
        session_id=session.session_id,
        agent_id="executor:stale",
        tool_name="write",
        tool_args={},
        risk_level="high",
        timeout_seconds=0.001,
    )
    time.sleep(0.01)

    report = run_multi_agent_maintenance(backend)

    assert report["expired_locks"] == 1
    assert report["expired_messages"] == 1
    assert report["timed_out_approvals"] == 1
    assert report["deadlocks"] == []


def test_session_view_includes_pending_tool_approvals_for_session() -> None:
    service = AgentTeamService(branch_service=None)
    session = service.create_session(user_id="user-1", goal="Review approval")
    service.coordination_backend.approval_queue.submit_pending(
        request_id="approval-visible",
        session_id=session.session_id,
        agent_id="executor:1",
        tool_name="write_text_artifact",
        tool_args={"path": "src/a.py"},
        risk_level="high",
        timeout_seconds=60,
    )

    view = service.get_session_view(session_id=session.session_id, user_id="user-1")

    assert [item["request_id"] for item in view["pending_tool_approvals"]] == ["approval-visible"]


def test_session_view_excludes_pending_tool_approvals_from_other_sessions() -> None:
    service = AgentTeamService(branch_service=None)
    session = service.create_session(user_id="user-1", goal="Isolate approvals")
    service.coordination_backend.approval_queue.submit_pending(
        request_id="approval-other",
        session_id="other-session",
        agent_id="executor:1",
        tool_name="write_text_artifact",
        tool_args={},
        risk_level="high",
        timeout_seconds=60,
    )

    view = service.get_session_view(session_id=session.session_id, user_id="user-1")

    assert view["pending_tool_approvals"] == []


def test_approval_decision_removes_request_from_pending_session_view() -> None:
    service = AgentTeamService(branch_service=None)
    session = service.create_session(user_id="user-1", goal="Decide approval")
    queue = service.coordination_backend.approval_queue
    queue.submit_pending(
        request_id="approval-decide",
        session_id=session.session_id,
        agent_id="executor:1",
        tool_name="write_text_artifact",
        tool_args={},
        risk_level="high",
        timeout_seconds=60,
    )

    queue.decide(request_id="approval-decide", approved=True, decided_by="reviewer")
    view = service.get_session_view(session_id=session.session_id, user_id="user-1")

    assert view["pending_tool_approvals"] == []


def test_failure_handler_flag_off_preserves_failed_task_status() -> None:
    service = AgentTeamService(
        branch_service=None,
        executor=_AlwaysFailExecutor(),
        settings=Settings(
            multi_agent_v2_enabled=True,
            multi_agent_failure_handler_enabled=False,
        ),
    )
    session = service.create_session(user_id="user-1", goal="Fail without handler")
    task = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal="Task should fail",
        create_branch=False,
    )

    _, tasks = service.run_ready_tasks_once(session_id=session.session_id, user_id="user-1")
    updated = {item.task_id: item for item in tasks}[task.task_id]

    assert updated.status == AgentTeamTaskStatus.FAILED
    assert updated.attempt == 1
    assert updated.last_error == "simulated execution failure"


def test_merge_warning_conflict_does_not_block_without_file_overlap() -> None:
    service = AgentTeamService(
        branch_service=None,
        settings=Settings(multi_agent_v2_enabled=True),
    )
    session = service.create_session(user_id="user-1", goal="Merge warning outputs")
    first = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal="Patch A",
        create_branch=False,
    )
    second = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.FRONTEND_EXECUTOR,
        goal="Patch B",
        create_branch=False,
    )
    reviewer = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.REVIEWER,
        goal="Review",
        create_branch=False,
    )
    for task in (first, second, reviewer):
        service.update_task(
            task_id=task.task_id,
            user_id="user-1",
            status=AgentTeamTaskStatus.DONE,
        )
    service.record_task_output(
        task_id=first.task_id,
        user_id="user-1",
        summary="The API should use retries.",
        changed_files=["src/api.py"],
    )
    service.record_task_output(
        task_id=second.task_id,
        user_id="user-1",
        summary="The API should not use retries.",
        changed_files=["apps/web/api.ts"],
    )
    service.record_task_output(
        task_id=reviewer.task_id,
        user_id="user-1",
        summary="Review evidence collected.",
    )

    bundle = service.prepare_merge_bundle(session_id=session.session_id, user_id="user-1")

    assert bundle.final_answer_status != AgentTeamFinalAnswerStatus.BLOCKED
    assert any("Merge conflict warning" in item for item in bundle.risk_items)


def test_directive_messages_survive_maintenance_cleanup() -> None:
    service = AgentTeamService(
        branch_service=None,
        settings=Settings(multi_agent_v2_enabled=True),
    )
    session = service.create_session(user_id="user-1", goal="Directive")
    bus = service.coordination_backend.message_bus
    bus.default_ttl_seconds = 0.001
    message_id = bus.publish(
        session_id=session.session_id,
        source_agent="orchestrator:1",
        target_agent="executor:1",
        message_type=AgentMessageType.DIRECTIVE,
        payload={"command": "pause"},
    )
    time.sleep(0.01)

    report = run_multi_agent_maintenance(service.coordination_backend)
    messages = bus.subscribe(session_id=session.session_id, agent_id="executor:1").poll()

    assert report["expired_messages"] == 0
    assert [message.message_id for message in messages] == [message_id]
