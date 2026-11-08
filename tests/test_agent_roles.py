from focus_agent.config import Settings
from focus_agent.delegation.roles import (
    AgentRole,
    RoleModelResolver,
    build_role_route_plan,
    infer_role_candidates,
)


def test_role_model_resolver_uses_role_override_then_helper_then_default():
    settings = Settings(
        model="openai:gpt-4.1-mini",
        helper_model="moonshot:kimi-k2.6",
        agent_role_planner_model="ollama:qwen2.5:7b",
    )
    resolver = RoleModelResolver(settings)

    assert resolver.resolve(AgentRole.PLANNER) == "ollama:qwen2.5:7b"
    assert resolver.resolve("critic") == "moonshot:kimi-k2.6"
    assert RoleModelResolver(Settings()).resolve("executor") == "openai:gpt-4.1-mini"


def test_role_model_resolver_keeps_executor_on_main_model_by_default():
    settings = Settings(
        model="openai:gpt-4.1-mini",
        helper_model="moonshot:kimi-k2.6",
    )
    resolver = RoleModelResolver(settings)

    assert resolver.resolve("executor") == "openai:gpt-4.1-mini"
    assert resolver.resolve("planner") == "moonshot:kimi-k2.6"


def test_build_role_route_plan_returns_disabled_plan_when_flag_is_off():
    plan = build_role_route_plan(
        settings=Settings(),
        task_text="implement runtime backend and tests",
        available_tool_names=("search_code", "read_file"),
        tool_policy="execution",
    )

    assert plan.enabled is False
    assert plan.decisions == []
    assert plan.legacy_execution_unchanged is True


def test_build_role_route_plan_records_governed_dry_run_decisions_when_enabled():
    settings = Settings(
        agent_role_routing_enabled=True,
        agent_role_orchestrator_model="openai:gpt-4.1-mini",
        agent_role_executor_model="moonshot:kimi-k2.6",
        agent_role_critic_model="ollama:qwen2.5:7b",
        agent_role_max_parallel_runs=2,
    )

    plan = build_role_route_plan(
        settings=settings,
        task_text="Implement backend runtime changes and verify tests.",
        available_tool_names=(
            "search_code",
            "read_file",
            "web_search",
            "apply_patch",
            "run_workspace_command",
            "write_text_artifact",
        ),
        tool_policy="execution",
    )

    assert plan.enabled is True
    assert plan.max_parallel_runs == 2
    assert [decision.role for decision in plan.decisions] == [
        AgentRole.ORCHESTRATOR,
        AgentRole.EXECUTOR,
        AgentRole.CRITIC,
    ]
    executor = plan.decisions[1]
    assert executor.model_id == "moonshot:kimi-k2.6"
    assert executor.depends_on == ["role:orchestrator"]
    assert executor.tool_governance.allowed_tools == [
        "search_code",
        "read_file",
        "apply_patch",
        "run_workspace_command",
        "write_text_artifact",
    ]
    assert executor.tool_governance.denied_tools == ["web_search"]
    assert executor.tool_governance.allow_workspace_write is True
    assert plan.decisions[2].model_id == "ollama:qwen2.5:7b"


def test_infer_role_candidates_respects_parallel_cap():
    candidates = infer_role_candidates(
        "Research the API, implement the backend, verify tests, and write docs.",
        max_parallel_runs=2,
    )

    assert candidates == [AgentRole.PLANNER, AgentRole.EXECUTOR]
