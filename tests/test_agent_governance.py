from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain.messages import AIMessage, HumanMessage
from langchain.tools import tool

from focus_agent.api.main import create_app
from focus_agent.api.route_utils.agent_governance_trajectory_responses import (
    _agent_governance_metrics_from_turns,
    _plan_meta_governance_payload,
)
from focus_agent.capabilities.tool_registry import ToolRegistry
from focus_agent.capabilities.tool_router import (
    build_capability_registry,
    build_tool_route_plan,
    build_toolset_registry,
)
from focus_agent.config import Settings
from focus_agent.core.branching import BranchRecord, BranchRole, BranchStatus
from focus_agent.core.request_context import RequestContext
from focus_agent.core.state import make_agent_state_record
from focus_agent.engine.graph_builder import _tools_for_policy, build_graph
from focus_agent.memory.curator import MemoryCurator
from focus_agent.repositories.governance_repository import InMemoryGovernanceRepository
from focus_agent.skills.registry import SkillRegistry, bundled_skills_dir


class _Hit:
    def __init__(self, key, value):
        self.key = key
        self.value = value


class _MemoryStore:
    def __init__(self, hits=None):
        self.hits = list(hits or [])
        self.put_calls = []

    def search(self, namespace, query, limit):  # noqa: ARG002
        return self.hits[:limit]

    def put(self, namespace, key, payload):
        self.put_calls.append((namespace, key, payload))


class _DecisionRepo:
    def list_turns(self, query):
        assert query.limit in {50, 1000, None}
        return [
            {
                "id": "turn-1",
                "request_id": "req-1",
                "trace_id": "trace-1",
                "thread_id": "thread-1",
                "root_thread_id": "root-1",
                "status": "succeeded",
                "plan_meta": {
                    "governance_records": [
                        make_agent_state_record(
                            "tool_intent_plan",
                            {
                                "policy": "live_web_research",
                                "preferred_first_tool": "web_search",
                                "source": "deterministic",
                            },
                            source="test",
                            request_id="req-1",
                            actor="agent_f",
                        ),
                        make_agent_state_record(
                            "tool_route_plan",
                            {
                                "enabled": True,
                                "role": "critic",
                                "tool_policy": "execution",
                                "allowed_tools": ["search_code"],
                                "denied_tools": ["write_text_artifact"],
                                "decisions": [],
                            },
                            source="test",
                            request_id="req-1",
                            actor="agent_f",
                        ),
                        make_agent_state_record(
                            "memory_curator_decision",
                            {
                                "enabled": True,
                                "branch_id": "branch-1",
                                "status": "needs_review",
                                "promoted_memory_ids": [],
                                "conflicts": [{"candidate_id": "branch-1:0"}],
                            },
                            source="test",
                        ),
                    ],
                    "tool_route_plan": {
                        "enabled": True,
                        "role": "critic",
                        "tool_policy": "execution",
                        "allowed_tools": ["search_code"],
                        "denied_tools": ["legacy_tool"],
                        "decisions": [],
                    },
                    "tool_intent_plan": {
                        "policy": "workspace_lookup",
                        "preferred_first_tool": "search_code",
                        "source": "legacy",
                    },
                    "memory_curator_decision": {
                        "enabled": True,
                        "branch_id": "branch-1",
                        "status": "needs_review",
                        "promoted_memory_ids": [],
                        "conflicts": [],
                    },
                    "agent_delegation_plan": {
                        "enabled": True,
                        "runs": [
                            {
                                "run_id": "run-1",
                                "task_id": "task-1",
                                "role": "executor",
                                "status": "completed",
                            }
                        ],
                    },
                    "model_route_decision": {
                        "enabled": True,
                        "mode": "observe",
                        "role": "executor",
                        "effective_model": "openai:gpt-4.1-mini",
                    },
                    "agent_failure_records": [
                        {
                            "failure_id": "failure-1",
                            "failure_type": "tool_denied",
                            "failed_role": "critic",
                        }
                    ],
                    "agent_review_queue": [
                        {
                            "item_id": "review-1",
                            "item_type": "workspace_write_with_high_risk_tool",
                            "status": "pending",
                        }
                    ],
                    "agent_task_ledger": {
                        "enabled": True,
                        "status": "planned",
                        "tasks": [
                            {
                                "task_id": "task-1",
                                "role": "executor",
                                "goal": "Produce evidence.",
                                "status": "completed",
                                "artifact_ids": ["artifact-1"],
                                "retry_count": 0,
                            }
                        ],
                    },
                    "delegated_artifacts": [
                        {
                            "artifact_id": "artifact-1",
                            "task_id": "task-1",
                            "role": "executor",
                            "kind": "evidence",
                            "title": "Evidence",
                            "status": "accepted",
                        }
                    ],
                    "critic_gate_result": {
                        "enabled": True,
                        "enforce": False,
                        "verdict": "pass",
                        "accepted_artifact_ids": ["artifact-1"],
                        "rejected_artifact_ids": [],
                    },
                },
            }
        ]

    def get_turn(self, _turn_id):
        return None

    def list_steps_by_turn_ids(self, _turn_ids):
        return {}

    def get_turn_stats(self, _query):
        return {"overview": {"turn_count": 1}, "by_status": []}


@tool
def search_code(query: str) -> str:
    """Search code."""
    return query


@tool
def read_file(path: str) -> str:
    """Read a workspace file."""
    return path


@tool
def write_text_artifact(title: str, content: str) -> str:
    """Write an artifact."""
    return f"{title}:{content}"


@tool
def web_search(query: str) -> str:
    """Search the web."""
    return query


@tool
def web_fetch(url: str) -> str:
    """Fetch a web page."""
    return url


@tool
def current_utc_time() -> str:
    """Return current UTC time."""
    return "2026-01-01T00:00:00Z"


@tool
def skills_list() -> str:
    """List skills."""
    return "plan,security-review"


@tool
def skill_view(name: str) -> str:
    """View a skill."""
    return name


write_text_artifact.metadata = {"side_effect": True, "side_effect_kind": "workspace_write"}
web_search.metadata = {"parallel_safe": True}
web_fetch.metadata = {"parallel_safe": True}
current_utc_time.metadata = {"parallel_safe": True}
search_code.metadata = {"parallel_safe": True}
read_file.metadata = {"parallel_safe": True}
skills_list.metadata = {"parallel_safe": True}
skill_view.metadata = {"parallel_safe": True}


def _branch_record(status=BranchStatus.ACTIVE):
    return BranchRecord(
        branch_id="branch-1",
        root_thread_id="root-1",
        parent_thread_id="root-1",
        child_thread_id="thread-branch-1",
        return_thread_id="root-1",
        owner_user_id="user-1",
        branch_name="Branch One",
        branch_role=BranchRole.EXECUTE,
        branch_depth=1,
        branch_status=status,
    )


def _with_stub_frontend(monkeypatch, tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setenv("WEB_APP_DIST_DIR", str(dist_dir))
    monkeypatch.setenv("WEB_APP_DEV_SERVER_URL", "")
    monkeypatch.setenv("AUTH_ENABLED", "false")


def _agent_governance_client(
    *,
    settings: Settings | None = None,
    repository: InMemoryGovernanceRepository | None = None,
) -> tuple[TestClient, InMemoryGovernanceRepository]:
    from focus_agent.api.routers.agent_governance import router

    resolved_settings = settings or Settings(auth_enabled=False)
    resolved_repository = repository or InMemoryGovernanceRepository()
    app = FastAPI()
    app.include_router(router)
    app.state.runtime = SimpleNamespace(
        settings=resolved_settings,
        skill_registry=SkillRegistry([bundled_skills_dir()]),
        governance_repository=resolved_repository,
        tool_registry=ToolRegistry(tools=(search_code, write_text_artifact)),
        trajectory_recorder=None,
        store=_MemoryStore(),
        graph=object(),
        repo=object(),
        branch_service=object(),
    )
    return TestClient(app), resolved_repository


def test_skill_selection_logs_feedback_and_preference() -> None:
    client, repository = _agent_governance_client()

    selection = client.post(
        "/v1/agent/skills/select",
        json={"message": "Please write an implementation plan.", "skill_hints": ["plan"]},
    )
    assert selection.status_code == 200
    selection_payload = selection.json()
    selection_id = selection_payload["selection_id"]

    selections = client.get("/v1/agent/skills/selections")
    feedback = client.post(
        f"/v1/agent/skills/selections/{selection_id}/feedback",
        json={"feedback": "useful", "reason": "matched planning work"},
    )
    preference = client.patch(
        "/v1/agent/skills/plan/preference",
        json={"state": "pinned", "metadata": {"scope": "composer"}},
    )
    catalog = client.get("/v1/agent/skills/catalog")

    assert selections.status_code == 200
    assert selections.json()["items"][0]["selection_id"] == selection_id
    assert selections.json()["items"][0]["activated_skill_ids"] == ["plan"]
    assert feedback.status_code == 200
    assert feedback.json()["item"]["feedback"] == "useful"
    assert preference.status_code == 200
    assert preference.json()["state"] == "pinned"
    plan_catalog_item = next(item for item in catalog.json()["items"] if item["skill_id"] == "plan")
    assert plan_catalog_item["preference"]["state"] == "pinned"
    assert repository.get_skill_selection_event(selection_id).feedback == "useful"


def test_skill_selection_event_logging_can_be_disabled() -> None:
    client, _repository = _agent_governance_client(
        settings=Settings(auth_enabled=False, skill_selection_event_log_enabled=False)
    )

    selection = client.post(
        "/v1/agent/skills/select",
        json={"message": "Please write an implementation plan.", "skill_hints": ["plan"]},
    )
    selections = client.get("/v1/agent/skills/selections")

    assert selection.status_code == 200
    assert selection.json()["selection_id"] is None
    assert selections.status_code == 200
    assert selections.json()["items"] == []


def test_context_explain_persists_evidence_for_listing() -> None:
    client, _repository = _agent_governance_client()

    explain = client.post(
        "/v1/agent/context/explain",
        json={
            "thread_id": "thread-1",
            "turn_id": "turn-1",
            "selected_memories": [{"memory_id": "mem-1", "summary": "Uses project fact."}],
            "excluded_memories": [{"memory_id": "mem-2", "reason": "stale"}],
            "token_counting": {"counting_backend": "tiktoken"},
            "risk_flags": ["high_drift"],
        },
    )
    listed = client.get("/v1/agent/context/evidence?thread_id=thread-1")

    assert explain.status_code == 200
    assert explain.json()["item"]["selected_memories"][0]["memory_id"] == "mem-1"
    assert listed.status_code == 200
    assert listed.json()["count"] == 1
    assert listed.json()["items"][0]["turn_id"] == "turn-1"
    assert listed.json()["items"][0]["risk_flags"] == ["high_drift"]


def test_tool_router_builds_capability_registry_and_denies_critic_writes():
    registry = ToolRegistry(tools=(search_code, write_text_artifact, web_search))

    capabilities = {item.name: item for item in build_capability_registry(registry)}
    plan = build_tool_route_plan(
        tool_registry=registry,
        role="critic",
        tool_policy="execution",
        available_tool_names=["search_code", "write_text_artifact", "web_search"],
    )

    assert capabilities["write_text_artifact"].requires_workspace_write is True
    assert "search_code" in plan.allowed_tools
    assert "write_text_artifact" in plan.denied_tools
    assert "web_search" in plan.denied_tools


def test_tool_router_respects_exposed_tool_names_for_turn_policy():
    registry = ToolRegistry(tools=(search_code, read_file, web_search))

    plan = build_tool_route_plan(
        tool_registry=registry,
        role="executor",
        tool_policy="workspace_lookup",
        available_tool_names=["search_code", "read_file", "web_search"],
        exposed_tool_names=["search_code"],
    )

    read_file_decision = next(item for item in plan.decisions if item.name == "read_file")
    web_search_decision = next(item for item in plan.decisions if item.name == "web_search")
    assert plan.allowed_tools == ["search_code"]
    assert read_file_decision.reason == "not_exposed_by_turn_policy"
    assert web_search_decision.reason == "policy_not_allowed:workspace_lookup"


def test_capability_registry_exposes_tool_quality_metadata():
    @tool
    def tuned_lookup(query: str) -> str:
        """Lookup tuned data."""
        return query

    tuned_lookup.metadata = {
        "toolset": "workspace",
        "parallel_safe": True,
        "cacheable": True,
        "requires_network": False,
        "sensitive_args": ("token",),
        "provider_id": "local-fixture",
        "usage_examples": ("Use for symbol lookup.",),
        "negative_examples": ("Do not use for live web research.",),
        "max_calls_per_turn": 1,
        "output_summary_contract": "Return compact snippets.",
        "intent_policies": ("workspace_lookup",),
        "allowed_roles": ("executor",),
    }

    capability = build_capability_registry(ToolRegistry(tools=(tuned_lookup,)))[0]

    assert capability.parallel_safe is True
    assert capability.cacheable is True
    assert capability.requires_network is False
    assert capability.sensitive_args == ["token"]
    assert capability.provider_id == "local-fixture"
    assert capability.usage_examples == ["Use for symbol lookup."]
    assert capability.negative_examples == ["Do not use for live web research."]
    assert capability.max_calls_per_turn == 1
    assert capability.output_summary_contract == "Return compact snippets."


def test_toolset_registry_summarizes_capability_groups():
    registry = ToolRegistry(tools=(search_code, write_text_artifact, web_search))

    toolsets = {item.name: item for item in build_toolset_registry(registry)}

    assert toolsets["workspace"].tools == ["search_code"]
    assert toolsets["workspace"].description == "Inspect repository files, code, and git state."
    assert toolsets["workspace"].provider_ids == ["builtin"]
    assert toolsets["workspace"].risk_levels == ["low"]
    assert "executor" in toolsets["workspace"].allowed_roles
    assert toolsets["web"].requires_network is True
    assert toolsets["artifact"].requires_workspace_write is True
    assert toolsets["artifact"].side_effect is True
    assert toolsets["artifact"].risk_levels == ["medium"]


def test_tool_router_matches_graph_policy_filtering_for_core_policies():
    @tool
    def approval_lookup(name: str) -> str:
        """Lookup that requires approval."""
        return name

    approval_lookup.metadata = {
        "requires_approval": True,
        "risk_level": "high",
        "intent_policies": ("execution",),
        "allowed_roles": ("executor",),
    }

    tools = [
        search_code,
        read_file,
        write_text_artifact,
        web_search,
        web_fetch,
        current_utc_time,
        approval_lookup,
    ]
    registry = ToolRegistry(tools=tuple(tools))

    for policy, role in (
        ("direct_answer", "executor"),
        ("workspace_lookup", "executor"),
        ("live_web_research", "planner"),
        ("execution", "executor"),
    ):
        graph_allowed = [item.name for item in _tools_for_policy(policy, tools, role=role)]
        route_plan = build_tool_route_plan(
            tool_registry=registry,
            role=role,
            tool_policy=policy,
            available_tool_names=[item.name for item in tools],
        )
        assert route_plan.allowed_tools == graph_allowed

    live_web_plan = build_tool_route_plan(
        tool_registry=registry,
        role="planner",
        tool_policy="live_web_research",
        available_tool_names=[item.name for item in tools],
    )
    assert live_web_plan.allowed_tools == ["web_search", "web_fetch", "current_utc_time"]

    mixed_readonly_names = [
        "search_code",
        "read_file",
        "web_search",
        "web_fetch",
        "current_utc_time",
        "write_text_artifact",
    ]
    mixed_graph_allowed = [
        item.name
        for item in _tools_for_policy("execution", tools, role="planner")
        if item.name in mixed_readonly_names
    ]
    mixed_plan = build_tool_route_plan(
        tool_registry=registry,
        role="planner",
        tool_policy="execution",
        available_tool_names=mixed_readonly_names,
    )
    assert mixed_plan.allowed_tools == mixed_graph_allowed
    assert {"search_code", "read_file", "web_search", "web_fetch", "current_utc_time"} <= set(
        mixed_plan.allowed_tools
    )
    assert "write_text_artifact" in mixed_plan.denied_tools

    execution_plan = build_tool_route_plan(
        tool_registry=registry,
        role="executor",
        tool_policy="execution",
        available_tool_names=[item.name for item in tools],
    )
    approval_decision = next(
        item for item in execution_plan.decisions if item.name == "approval_lookup"
    )
    assert approval_decision.allowed is True
    assert approval_decision.reason == "approval_required"
    assert "approval_lookup" in execution_plan.allowed_tools


def test_graph_tool_router_filters_bound_tools_for_critic(monkeypatch):
    captured = {}

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

    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: FakeModel(),
    )
    graph = build_graph(
        settings=Settings(
            plan_act_reflect_enabled=False,
            agent_tool_router_enabled=True,
            agent_tool_router_enforce=True,
        ),
        tool_registry=ToolRegistry(tools=(search_code, write_text_artifact)),
    )

    result = graph.invoke(
        {
            "messages": [HumanMessage(content="验证并修改代码。")],
            "role_route_plan": {
                "decisions": [
                    {"role": "orchestrator"},
                    {"role": "critic"},
                ]
            },
        },
        context=RequestContext(user_id="user-1", root_thread_id="root-1"),
        version="v2",
    )

    assert captured["bound_tools"] == ["search_code"]
    assert result.value["tool_route_plan"]["role"] == "critic"
    assert "write_text_artifact" in result.value["tool_route_plan"]["denied_tools"]
    assert any(
        record["name"] == "tool_route_plan" and record["mirror_key"] == "tool_route_plan"
        for record in result.value["governance_records"]
    )


def test_memory_curator_promotes_clean_branch_findings_and_blocks_discarded_branch():
    curator = MemoryCurator(store=_MemoryStore())
    context = RequestContext(user_id="user-1", root_thread_id="root-1", branch_id="branch-1")

    decision = curator.evaluate_branch_promotion(
        branch_record=_branch_record(),
        findings=[
            {
                "finding": "Use the agent governance console for tool routing.",
                "evidence_refs": ["doc-1"],
            }
        ],
        context=context,
        auto_promote=True,
    )
    discarded = curator.evaluate_branch_promotion(
        branch_record=_branch_record(status=BranchStatus.DISCARDED),
        findings=[{"finding": "This should not promote."}],
        context=context,
        auto_promote=True,
    )

    assert decision.status == "ready"
    assert len(decision.candidates) == 1
    assert discarded.status == "blocked"
    assert discarded.candidates == []


def test_memory_curator_marks_semantic_conflict_for_review():
    store = _MemoryStore(
        [
            _Hit(
                "existing-1",
                {
                    "memory_id": "existing-1",
                    "kind": "branch_finding",
                    "scope": "root_thread",
                    "visibility": "shared",
                    "content": "Use the agent governance console for tool routing.",
                    "summary": "Use the agent governance console for tool routing.",
                    "promoted_to_main": True,
                    "root_thread_id": "root-1",
                },
            )
        ]
    )
    curator = MemoryCurator(store=store)

    decision = curator.evaluate_branch_promotion(
        branch_record=_branch_record(),
        findings=[{"finding": "Use the agent governance console for tool routing with review."}],
        context=RequestContext(user_id="user-1", root_thread_id="root-1", branch_id="branch-1"),
        auto_promote=True,
    )

    assert decision.status == "needs_review"
    assert len(decision.conflicts) == 1
    assert decision.candidates == []


def test_governance_api_metrics_use_descriptors_with_legacy_fallback():
    rows = [
        {
            "plan_meta": {
                "governance_records": [
                    make_agent_state_record(
                        "tool_route_plan",
                        {"denied_tools": ["record_tool"], "enforce": True},
                        source="test",
                    )
                ],
                "tool_route_plan": {"denied_tools": ["legacy_tool"], "enforce": False},
                "tool_intent_plan": {
                    "policy": "live_web_research",
                    "preferred_first_tool": "web_search",
                },
            }
        },
        {
            "plan_meta": {
                "memory_curator_decision": {
                    "promoted_memory_ids": ["mem-1"],
                    "conflicts": [{"candidate_id": "candidate-1"}],
                }
            }
        },
    ]

    metrics = _agent_governance_metrics_from_turns(rows)

    assert _plan_meta_governance_payload(rows[0]["plan_meta"], "tool_route_plan")[
        "denied_tools"
    ] == ["record_tool"]
    assert metrics["tool_router_denied"] == 1
    assert metrics["tool_router_enforced"] == 1
    assert metrics["tool_intent_live_web_research"] == 1
    assert metrics["tool_intent_first_tool"] == 1
    assert metrics["memory_promotions"] == 1
    assert metrics["memory_conflicts"] == 1


def test_agent_governance_api_shapes(monkeypatch, tmp_path):
    _with_stub_frontend(monkeypatch, tmp_path)
    app = create_app()
    app.state.runtime = SimpleNamespace(
        settings=Settings(
            auth_enabled=False,
            agent_role_routing_enabled=True,
            agent_role_max_parallel_runs=5,
            agent_memory_curator_enabled=True,
            agent_tool_router_enabled=True,
            agent_delegation_enabled=True,
            agent_model_router_enabled=True,
            agent_self_repair_enabled=True,
            agent_review_queue_enabled=True,
            agent_task_ledger_enabled=True,
            agent_artifact_synthesis_enabled=True,
            agent_critic_gate_enabled=True,
        ),
        tool_registry=ToolRegistry(
            tools=(search_code, write_text_artifact, web_search, skills_list, skill_view)
        ),
        trajectory_recorder=_DecisionRepo(),
        store=_MemoryStore(),
        graph=object(),
        repo=object(),
        branch_service=object(),
        skill_registry=object(),
    )
    client = TestClient(app)

    capabilities = client.get("/v1/agent/capabilities")
    toolsets = client.get("/v1/agent/toolsets")
    role_route = client.post(
        "/v1/agent/roles/dry-run",
        json={
            "message": "Plan skill selection and branch suggestion before implementation.",
            "scene": "execution",
            "available_tools": ["skills_list", "skill_view", "search_code", "write_text_artifact"],
        },
    )
    route = client.post(
        "/v1/agent/tool-router/route",
        json={
            "role": "critic",
            "tool_policy": "execution",
            "available_tools": ["search_code", "write_text_artifact"],
        },
    )
    memory_policy = client.get("/v1/agent/memory/curator/policy")
    memory_eval = client.post(
        "/v1/agent/memory/curator/evaluate",
        json={
            "root_thread_id": "root-1",
            "branch_id": "branch-1",
            "findings": [{"finding": "Promote this branch finding."}],
        },
    )
    tool_decisions = client.get("/v1/agent/tool-router/decisions")
    memory_decisions = client.get("/v1/agent/memory/curator/decisions")
    delegation_policy = client.get("/v1/agent/delegation/policy")
    delegation_plan = client.post(
        "/v1/agent/delegation/plan", json={"message": "Plan and implement delegation."}
    )
    delegation_runs = client.get("/v1/agent/delegation/runs")
    model_policy = client.get("/v1/agent/model-router/policy")
    model_route = client.post("/v1/agent/model-router/route", json={"role": "critic"})
    model_decisions = client.get("/v1/agent/model-router/decisions")
    failures = client.get("/v1/agent/self-repair/failures")
    promote_preview = client.post(
        "/v1/agent/self-repair/promote-preview",
        json={
            "failures": [
                {"failure_id": "failure-1", "failure_type": "tool_denied", "failed_role": "critic"}
            ]
        },
    )
    review_queue = client.get("/v1/agent/review-queue")
    review_approve = client.post("/v1/agent/review-queue/review-1/approve")
    review_reject = client.post("/v1/agent/review-queue/review-1/reject")
    task_ledger_policy = client.get("/v1/agent/task-ledger/policy")
    task_ledger_plan = client.post(
        "/v1/agent/task-ledger/plan", json={"message": "Plan task ledger handoff."}
    )
    task_ledger_runs = client.get("/v1/agent/task-ledger/runs")
    artifacts = client.get("/v1/agent/artifacts")
    synthesis = client.post(
        "/v1/agent/artifacts/synthesize",
        json={
            "artifacts": [
                {
                    "artifact_id": "artifact-1",
                    "task_id": "task-1",
                    "role": "executor",
                    "kind": "evidence",
                    "title": "Evidence",
                    "status": "accepted",
                }
            ]
        },
    )
    critic_verdicts = client.get("/v1/agent/critic/verdicts")
    critic_eval = client.post(
        "/v1/agent/critic/evaluate",
        json={
            "ledger": {
                "enabled": True,
                "tasks": [{"task_id": "task-1", "role": "executor", "goal": "Produce evidence."}],
            },
            "artifacts": [
                {
                    "artifact_id": "artifact-1",
                    "task_id": "task-1",
                    "role": "executor",
                    "kind": "evidence",
                    "title": "Evidence",
                    "status": "accepted",
                }
            ],
        },
    )
    metrics = client.get("/metrics")

    assert capabilities.status_code == 200
    assert capabilities.json()["count"] >= 3
    assert toolsets.status_code == 200
    assert any(item["name"] == "workspace" for item in toolsets.json()["items"])
    role_plan = role_route.json()["plan"]
    assert role_plan["legacy_execution_unchanged"] is True
    assert any(decision["role"] == "skill_scout" for decision in role_plan["decisions"])
    skill_decision = next(
        decision for decision in role_plan["decisions"] if decision["role"] == "skill_scout"
    )
    assert skill_decision["run_isolation_key"] == "role:skill_scout"
    assert skill_decision["tool_governance"]["allowed_tools"] == ["skills_list", "skill_view"]
    assert route.json()["plan"]["role"] == "critic"
    assert "write_text_artifact" in route.json()["plan"]["denied_tools"]
    assert memory_policy.json()["enabled"] is True
    assert memory_eval.json()["decision"]["status"] == "ready"
    assert tool_decisions.json()["count"] == 1
    assert tool_decisions.json()["items"][0]["denied_tools"] == ["write_text_artifact"]
    assert memory_decisions.json()["count"] == 1
    assert memory_decisions.json()["items"][0]["conflicts"] == [{"candidate_id": "branch-1:0"}]
    assert delegation_policy.json()["enabled"] is True
    assert delegation_plan.json()["plan"]["enabled"] is True
    assert delegation_runs.json()["items"][0]["run_id"] == "run-1"
    assert model_policy.json()["enabled"] is True
    assert model_route.json()["decision"]["role"] == "critic"
    assert model_decisions.json()["count"] == 1
    assert failures.json()["items"][0]["failure_type"] == "tool_denied"
    assert promote_preview.json()["preview"]["candidates"][0]["tags"][0] == "agent_delegation"
    assert review_queue.json()["items"][0]["item_id"] == "review-1"
    assert review_approve.json()["item"]["status"] == "approved"
    assert review_reject.json()["item"]["status"] == "rejected"
    assert task_ledger_policy.json()["enabled"] is True
    assert task_ledger_plan.json()["ledger"]["enabled"] is True
    assert task_ledger_runs.json()["items"][0]["task_id"] == "task-1"
    assert artifacts.json()["items"][0]["artifact_id"] == "artifact-1"
    assert synthesis.json()["result"]["accepted_artifact_ids"] == ["artifact-1"]
    assert critic_verdicts.json()["items"][0]["verdict"] == "pass"
    assert critic_eval.json()["result"]["verdict"] == "pass"
    assert "focus_agent_tool_router_denied_count 1" in metrics.text
    assert "focus_agent_tool_intent_live_web_research_count 1" in metrics.text
    assert "focus_agent_tool_intent_first_tool_count 1" in metrics.text
    assert "focus_agent_memory_conflict_count 1" in metrics.text
    assert "focus_agent_delegation_run_count 1" in metrics.text
    assert "focus_agent_review_pending_count 1" in metrics.text
    assert "focus_agent_task_ledger_task_count 1" in metrics.text
    assert "focus_agent_delegated_artifact_count 1" in metrics.text
