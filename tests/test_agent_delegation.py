from focus_agent.agent_delegation import (
    apply_review_decision,
    build_agent_delegation_plan,
    build_failure_records,
    build_model_route_decision,
    build_review_queue,
    build_self_repair_preview,
)
from focus_agent.agent_roles import build_role_route_plan
from focus_agent.config import Settings


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
    assert all(run.status == "completed" for run in plan.runs)
    assert plan.legacy_execution_unchanged is False


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
