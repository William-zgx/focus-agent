from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from langchain.messages import AIMessage, HumanMessage
from langchain.tools import tool

from focus_agent.api.main import create_app
from focus_agent.agent_roles import (
    AgentRole,
    RoleModelResolver,
    build_role_route_plan,
    infer_role_candidates,
)
from focus_agent.capabilities.tool_registry import ToolRegistry
from focus_agent.config import Settings
from focus_agent.core.request_context import RequestContext
from focus_agent.engine.graph_builder import build_graph


class _RoleDecisionRepo:
    def list_turns(self, query):
        assert query.limit == 50
        return [
            {
                "id": "turn-1",
                "request_id": "req-1",
                "trace_id": "trace-1",
                "thread_id": "thread-1",
                "root_thread_id": "root-1",
                "status": "succeeded",
                "plan_meta": {
                    "role_route_plan": {
                        "enabled": True,
                        "route_reason": "Dry-run route selected 2 delegated role run(s).",
                        "max_parallel_runs": 2,
                        "orchestrator_model_id": "openai:gpt-4.1-mini",
                        "decisions": [
                            {"role": "orchestrator", "model_id": "openai:gpt-4.1-mini"},
                            {"role": "executor", "model_id": "openai:gpt-4.1-mini"},
                        ],
                    }
                },
            }
        ]

    def get_turn(self, _turn_id):
        return None

    def list_steps_by_turn_ids(self, _turn_ids):
        return {}

    def get_turn_stats(self, _query):
        return {}


def _with_stub_frontend(monkeypatch, tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setenv("WEB_APP_DIST_DIR", str(dist_dir))
    monkeypatch.setenv("WEB_APP_DEV_SERVER_URL", "")
    monkeypatch.setenv("AUTH_ENABLED", "false")


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
        available_tool_names=("search_code", "read_file", "web_search", "write_text_artifact"),
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


def test_graph_default_off_does_not_record_role_route_plan(monkeypatch):
    class FakeRunnable:
        def with_config(self, _config):
            return self

        def invoke(self, _prompt_messages):
            return AIMessage(content="done")

    class FakeModel:
        def bind_tools(self, _tools):
            raise AssertionError("direct answer should not bind tools")

        def with_config(self, _config):
            return FakeRunnable()

    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: FakeModel(),
    )
    graph = build_graph(
        settings=Settings(plan_act_reflect_enabled=False),
        tool_registry=ToolRegistry(tools=()),
    )

    result = graph.invoke(
        {"messages": [HumanMessage(content="用一句话解释 role routing。")]},
        context=RequestContext(user_id="user-1", root_thread_id="thread-1"),
        version="v2",
    )

    assert result.value.get("role_route_plan") is None


def test_graph_enabled_records_role_route_plan_without_changing_model_path(monkeypatch):
    captured: dict[str, object] = {}

    class FakeRunnable:
        def with_config(self, _config):
            return self

        def invoke(self, _prompt_messages):
            return AIMessage(content="done")

    class FakeModel:
        def bind_tools(self, bound_tools):
            captured["bound_tools"] = [item.name for item in bound_tools]
            return FakeRunnable()

        def with_config(self, _config):
            return FakeRunnable()

    def fake_create_chat_model(model_id, **kwargs):
        captured["model_id"] = model_id
        captured["kwargs"] = kwargs
        return FakeModel()

    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        fake_create_chat_model,
    )

    @tool
    def search_code(query: str) -> str:
        """Search code."""
        return query

    settings = Settings(
        model="openai:gpt-4.1-mini",
        agent_role_routing_enabled=True,
        agent_role_executor_model="moonshot:kimi-k2.6",
        plan_act_reflect_enabled=False,
    )
    graph = build_graph(settings=settings, tool_registry=ToolRegistry(tools=(search_code,)))

    result = graph.invoke(
        {"messages": [HumanMessage(content="实现 backend runtime role routing。")]},
        context=RequestContext(user_id="user-1", root_thread_id="thread-1"),
        version="v2",
    )

    plan = result.value["role_route_plan"]
    assert plan["enabled"] is True
    assert plan["decisions"][1]["role"] == "executor"
    assert plan["decisions"][1]["model_id"] == "moonshot:kimi-k2.6"
    assert captured["model_id"] == "openai:gpt-4.1-mini"
    assert captured["bound_tools"] == ["search_code"]


def test_agent_role_policy_dry_run_and_decisions_api(monkeypatch, tmp_path):
    _with_stub_frontend(monkeypatch, tmp_path)
    app = create_app()
    app.state.runtime = SimpleNamespace(
        settings=Settings(
            auth_enabled=False,
            agent_role_routing_enabled=True,
            agent_role_max_parallel_runs=2,
            helper_model="moonshot:kimi-k2.6",
        ),
        tool_registry=SimpleNamespace(
            tools=(
                SimpleNamespace(name="search_code"),
                SimpleNamespace(name="read_file"),
                SimpleNamespace(name="web_search"),
            )
        ),
        trajectory_recorder=_RoleDecisionRepo(),
        graph=object(),
        repo=object(),
        branch_service=object(),
        skill_registry=object(),
    )
    client = TestClient(app)

    policy_response = client.get("/v1/agent/roles/policy")
    dry_run_response = client.post(
        "/v1/agent/roles/dry-run",
        json={
            "message": "Plan implementation, modify backend code, and verify tests.",
            "available_tools": ["search_code", "read_file", "web_search"],
        },
    )
    decisions_response = client.get("/v1/agent/roles/decisions")

    assert policy_response.status_code == 200
    assert policy_response.json()["role_models"]["executor"] == "openai:gpt-4.1-mini"
    assert policy_response.json()["role_models"]["planner"] == "moonshot:kimi-k2.6"
    assert dry_run_response.status_code == 200
    decisions = dry_run_response.json()["plan"]["decisions"]
    assert decisions[0]["role"] == "orchestrator"
    assert [item["role"] for item in decisions[1:]] == ["planner", "executor"]
    assert decisions_response.status_code == 200
    assert decisions_response.json()["items"][0]["decisions"][1]["role"] == "executor"
