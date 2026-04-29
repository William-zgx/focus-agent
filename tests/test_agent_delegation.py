from __future__ import annotations

from threading import Lock
import time

from langchain.messages import AIMessage

from focus_agent.agent_delegation import (
    AgentTask,
    apply_review_decision,
    build_agent_delegation_plan,
    build_failure_records,
    build_model_route_decision,
    build_review_queue,
    build_self_repair_preview,
)
from focus_agent.agent_execution import (
    FakeDelegatedRunExecutor,
    SubagentRegistry,
    executor_for_mode,
    run_delegated_tasks,
)
from focus_agent.agent_roles import AgentRole, build_role_route_plan
from focus_agent.config import Settings

class RecordingFakeModel:
    def __init__(self, content: str = "delegated artifact", *, error: Exception | None = None, delay: float = 0.0):
        self.content = content
        self.error = error
        self.delay = delay
        self.calls: list[list[object]] = []
        self.active_calls = 0
        self.max_active_calls = 0
        self._lock = Lock()

    def invoke(self, messages):
        with self._lock:
            self.calls.append(list(messages))
            self.active_calls += 1
            self.max_active_calls = max(self.max_active_calls, self.active_calls)
        try:
            if self.delay:
                time.sleep(self.delay)
            if self.error is not None:
                raise self.error
            return AIMessage(content=self.content)
        finally:
            with self._lock:
                self.active_calls -= 1

    def with_config(self, _config):
        return self

    def bind_tools(self, _tools):
        return self


def _delegated_task(task_id: str, *, role: AgentRole = AgentRole.EXECUTOR) -> AgentTask:
    return AgentTask(
        task_id=task_id,
        role=role,
        goal=f"Goal for {task_id}",
        allowed_tools=["search_code"],
        acceptance_criteria=["return a traceable artifact"],
        run_isolation_key=f"role:{role.value}:{task_id}",
    )


def test_delegation_default_off_keeps_legacy_execution_safe():
    plan = build_agent_delegation_plan(
        settings=Settings(),
        task_text="Implement and verify delegation runtime.",
        available_tool_names=["search_code"],
    )

    assert plan.enabled is False
    assert plan.legacy_execution_unchanged is True
    assert plan.tasks == []


def test_delegation_builds_role_tasks_when_enabled():
    settings = Settings(
        agent_role_routing_enabled=True,
        agent_delegation_enabled=True,
        agent_delegation_enforce=True,
        agent_role_max_parallel_runs=3,
    )
    plan = build_agent_delegation_plan(
        settings=settings,
        task_text="Plan, implement, and verify the Agent delegation runtime.",
        available_tool_names=["search_code", "write_text_artifact"],
        tool_policy="execution",
    )

    roles = [task.role.value for task in plan.tasks]
    assert plan.enabled is True
    assert plan.enforce is True
    assert "orchestrator" in roles
    assert "planner" in roles
    assert "executor" in roles
    assert all(run.status == "planned" for run in plan.runs)
    assert plan.legacy_execution_unchanged is True


def test_delegation_contract_fields_and_observe_mode_do_not_complete_runs():
    settings = Settings(
        agent_role_routing_enabled=True,
        agent_delegation_enabled=True,
        agent_delegation_enforce=True,
    )
    plan = build_agent_delegation_plan(
        settings=settings,
        task_text="Implement and verify the runtime.",
        available_tool_names=["search_code", "write_text_artifact"],
        tool_policy="execution",
    )

    executor_task = next(task for task in plan.tasks if task.role == AgentRole.EXECUTOR)

    assert plan.execution_mode == "observe"
    assert all(run.status == "planned" for run in plan.runs)
    assert executor_task.max_turns >= 1
    assert executor_task.timeout_seconds > 0
    assert executor_task.max_depth >= 0
    assert executor_task.run_isolation_key == "role:executor"
    assert executor_task.requires_workspace_write is True


def test_fake_delegated_executor_produces_completion_result_and_artifact():
    settings = Settings(agent_delegation_execution_mode="fake")
    task = AgentTask(
        task_id="task-1-executor",
        role=AgentRole.EXECUTOR,
        goal="Produce deterministic delegated evidence.",
        allowed_tools=["search_code"],
        acceptance_criteria=["evidence is traceable"],
        run_isolation_key="role:executor",
    )

    results = run_delegated_tasks(
        tasks=[task],
        registry=SubagentRegistry.from_settings(settings),
        executor=FakeDelegatedRunExecutor(),
    )

    assert len(results) == 1
    assert results[0].status == "completed"
    assert results[0].artifacts[0].summary.startswith("Fake delegated executor run completed")
    assert results[0].to_agent_run().status == "completed"


def test_fake_delegated_executor_blocks_exhausted_budget_before_completion():
    settings = Settings(agent_delegation_execution_mode="fake")
    task = AgentTask(
        task_id="task-1-executor",
        role=AgentRole.EXECUTOR,
        goal="This should be blocked.",
        max_turns=0,
    )

    results = run_delegated_tasks(
        tasks=[task],
        registry=SubagentRegistry.from_settings(settings),
        executor=FakeDelegatedRunExecutor(),
    )

    assert results[0].status == "needs_review"
    assert "max_turns budget is exhausted" in str(results[0].error)
    assert results[0].artifacts == []

def test_inline_and_background_execution_modes_are_not_stubbed():
    inline = executor_for_mode("inline")
    background = executor_for_mode("background")

    assert inline is not None
    assert background is not None
    assert type(inline).__name__ != "StubDelegatedRunExecutor"
    assert type(background).__name__ != "StubDelegatedRunExecutor"


def test_inline_executor_invokes_injected_model_and_returns_completed_artifact():
    model = RecordingFakeModel("inline delegated result")
    executor = executor_for_mode("inline", model=model)

    results = run_delegated_tasks(
        tasks=[_delegated_task("task-inline")],
        registry=SubagentRegistry.from_settings(Settings(agent_delegation_execution_mode="inline")),
        executor=executor,
    )

    assert len(model.calls) == 1
    assert results[0].status == "completed"
    assert results[0].execution_mode == "inline"
    assert results[0].artifacts
    assert results[0].artifacts[0].summary == "inline delegated result"


def test_inline_executor_model_exception_becomes_failed_run_result():
    model = RecordingFakeModel(error=RuntimeError("model exploded"))
    executor = executor_for_mode("inline", model=model)

    results = run_delegated_tasks(
        tasks=[_delegated_task("task-inline-fail")],
        registry=SubagentRegistry.from_settings(Settings(agent_delegation_execution_mode="inline")),
        executor=executor,
    )

    assert len(model.calls) == 1
    assert results[0].status == "failed"
    assert results[0].execution_mode == "inline"
    assert "model exploded" in str(results[0].error)
    assert results[0].artifacts == []


def test_background_executor_runs_all_tasks_with_bounded_workers_and_preserves_order():
    model = RecordingFakeModel("background delegated result", delay=0.02)
    executor = executor_for_mode("background", model=model, max_workers=2)
    tasks = [_delegated_task(f"task-background-{index}") for index in range(4)]

    results = run_delegated_tasks(
        tasks=tasks,
        registry=SubagentRegistry.from_settings(Settings(agent_delegation_execution_mode="background")),
        executor=executor,
        max_parallel_runs=2,
    )

    assert [result.task_id for result in results] == [task.task_id for task in tasks]
    assert all(result.status == "completed" for result in results)
    assert all(result.execution_mode == "background" for result in results)
    assert len(model.calls) == len(tasks)
    assert 1 < model.max_active_calls <= 2


def test_model_router_observe_and_enforce_modes():
    observe = build_model_route_decision(
        settings=Settings(
            model="openai:gpt-4.1-mini",
            helper_model="openai:deepseek-chat",
            agent_model_router_enabled=True,
            agent_model_router_mode="observe",
            agent_role_planner_model="openai:gpt-4.1",
        ),
        role="planner",
        selected_model="openai:gpt-4.1-mini",
        task_text="Design the architecture.",
    )
    enforce = build_model_route_decision(
        settings=Settings(
            model="openai:gpt-4.1-mini",
            agent_model_router_enabled=True,
            agent_model_router_mode="enforce",
            agent_role_critic_model="openai:deepseek-chat",
        ),
        role="critic",
        selected_model="openai:gpt-4.1-mini",
    )

    assert observe.effective_model == "openai:gpt-4.1-mini"
    assert observe.recommended_model == "openai:gpt-4.1"
    assert enforce.effective_model == "openai:deepseek-chat"


def test_self_repair_preview_and_review_queue_from_failures():
    failure_records = build_failure_records(
        delegation_plan={"tasks": [{"task_id": "task-1-executor"}]},
        tool_route_plan={
            "role": "critic",
            "denied_tools": ["write_text_artifact"],
            "enforce": True,
        },
        model_route_decision={"effective_model": "openai:deepseek-chat"},
    )
    preview = build_self_repair_preview(failures=failure_records)
    queue = build_review_queue(
        settings=Settings(agent_review_queue_enabled=True),
        tool_route_plan={"role": "critic", "denied_tools": ["write_text_artifact"]},
        agent_failure_records=[item.model_dump(mode="json") for item in failure_records],
    )
    approved = apply_review_decision(queue[0].model_dump(mode="json"), approved=True)

    assert failure_records[0].failure_type == "tool_denied"
    assert preview.candidates[0]["tags"] == ["agent_delegation", "self_repair", "tool_denied"]
    assert queue[0].item_type == "workspace_write_with_high_risk_tool"
    assert approved.status == "approved"


def test_autonomy_governance_observe_first_reports_skill_branch_and_risk_policy():
    settings = Settings(
        agent_role_routing_enabled=True,
        agent_role_max_parallel_runs=5,
        agent_delegation_enabled=True,
        agent_model_router_enabled=True,
        agent_review_queue_enabled=True,
        model="openai:gpt-4.1-mini",
        helper_model="openai:gpt-4.1",
    )
    route_plan = build_role_route_plan(
        settings=settings,
        task_text="Plan skill selection, branch suggestion, implementation, and risk review.",
        available_tool_names=[
            "skills_list",
            "skill_view",
            "search_code",
            "write_text_artifact",
            "git_diff",
        ],
        tool_policy="execution",
    )
    delegation = build_agent_delegation_plan(
        settings=settings,
        task_text="Plan skill selection, branch suggestion, implementation, and risk review.",
        role_route_plan=route_plan.model_dump(mode="json"),
        available_tool_names=[
            "skills_list",
            "skill_view",
            "search_code",
            "write_text_artifact",
            "git_diff",
        ],
        tool_policy="execution",
    )
    model_route = build_model_route_decision(
        settings=settings,
        role="executor",
        selected_model="openai:gpt-4.1-mini",
        tool_risk="high",
    )
    failures = build_failure_records(
        delegation_plan=delegation.model_dump(mode="json"),
        tool_route_plan={
            "role": "critic",
            "denied_tools": ["write_text_artifact"],
            "decisions": [{"name": "write_text_artifact", "allowed": False, "reason": "critic_no_workspace_write"}],
        },
        model_route_decision=model_route.model_dump(mode="json"),
    )
    review_queue = build_review_queue(
        settings=settings,
        tool_route_plan={
            "role": "critic",
            "denied_tools": ["write_text_artifact"],
            "decisions": [{"name": "write_text_artifact", "allowed": False, "reason": "critic_no_workspace_write"}],
        },
        agent_failure_records=[item.model_dump(mode="json") for item in failures],
    )

    skill_task = next(task for task in delegation.tasks if task.role.value == "skill_scout")
    skill_decision = next(decision for decision in delegation.decisions if decision.role.value == "skill_scout")

    assert delegation.enabled is True
    assert delegation.enforce is False
    assert delegation.legacy_execution_unchanged is True
    assert all(run.status == "planned" for run in delegation.runs)
    assert skill_task.allowed_tools == ["skills_list", "skill_view"]
    assert skill_task.memory_scope == "thread"
    assert skill_decision.payload["run_isolation_key"] == "role:skill_scout"
    assert model_route.mode == "observe"
    assert model_route.effective_model == "openai:gpt-4.1-mini"
    assert "High-risk tool usage" in model_route.route_reason
    assert failures[0].failure_type == "tool_denied"
    assert review_queue[0].item_type == "workspace_write_with_high_risk_tool"
