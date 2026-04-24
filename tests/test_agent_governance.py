from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from langchain.messages import AIMessage, HumanMessage
from langchain.tools import tool

from focus_agent.api.main import create_app
from focus_agent.capabilities.tool_registry import ToolRegistry
from focus_agent.capabilities.tool_router import build_capability_registry, build_tool_route_plan
from focus_agent.config import Settings
from focus_agent.core.branching import BranchRecord, BranchRole, BranchStatus
from focus_agent.core.request_context import RequestContext
from focus_agent.engine.graph_builder import build_graph
from focus_agent.memory.curator import MemoryCurator


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
        assert query.limit in {50, None}
        return [
            {
                "id": "turn-1",
                "request_id": "req-1",
                "trace_id": "trace-1",
                "thread_id": "thread-1",
                "root_thread_id": "root-1",
                "status": "succeeded",
                "plan_meta": {
                    "tool_route_plan": {
                        "enabled": True,
                        "role": "critic",
                        "tool_policy": "execution",
                        "allowed_tools": ["search_code"],
                        "denied_tools": ["write_text_artifact"],
                        "decisions": [],
                    },
                    "memory_curator_decision": {
                        "enabled": True,
                        "branch_id": "branch-1",
                        "status": "needs_review",
                        "promoted_memory_ids": [],
                        "conflicts": [{"candidate_id": "branch-1:0"}],
                    },
                    "agent_delegation_plan": {
                        "enabled": True,
                        "runs": [{"run_id": "run-1", "task_id": "task-1", "role": "executor", "status": "completed"}],
                    },
                    "model_route_decision": {
                        "enabled": True,
                        "mode": "observe",
                        "role": "executor",
                        "effective_model": "openai:gpt-4.1-mini",
                    },
                    "agent_failure_records": [
                        {"failure_id": "failure-1", "failure_type": "tool_denied", "failed_role": "critic"}
                    ],
                    "agent_review_queue": [
                        {"item_id": "review-1", "item_type": "workspace_write_with_high_risk_tool", "status": "pending"}
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
def write_text_artifact(title: str, content: str) -> str:
    """Write an artifact."""
    return f"{title}:{content}"


@tool
def web_search(query: str) -> str:
    """Search the web."""
    return query


write_text_artifact.metadata = {"side_effect": True, "side_effect_kind": "workspace_write"}
web_search.metadata = {"parallel_safe": True}
search_code.metadata = {"parallel_safe": True}


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


def test_memory_curator_promotes_clean_branch_findings_and_blocks_discarded_branch():
    curator = MemoryCurator(store=_MemoryStore())
    context = RequestContext(user_id="user-1", root_thread_id="root-1", branch_id="branch-1")

    decision = curator.evaluate_branch_promotion(
        branch_record=_branch_record(),
        findings=[{"finding": "Use the agent governance console for tool routing.", "evidence_refs": ["doc-1"]}],
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


def test_agent_governance_api_shapes(monkeypatch, tmp_path):
    _with_stub_frontend(monkeypatch, tmp_path)
    app = create_app()
    app.state.runtime = SimpleNamespace(
        settings=Settings(
            auth_enabled=False,
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
        tool_registry=ToolRegistry(tools=(search_code, write_text_artifact, web_search)),
        trajectory_recorder=_DecisionRepo(),
        store=_MemoryStore(),
        graph=object(),
        repo=object(),
        branch_service=object(),
        skill_registry=object(),
    )
    client = TestClient(app)

    capabilities = client.get("/v1/agent/capabilities")
    route = client.post(
        "/v1/agent/tool-router/route",
        json={"role": "critic", "tool_policy": "execution", "available_tools": ["search_code", "write_text_artifact"]},
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
    delegation_plan = client.post("/v1/agent/delegation/plan", json={"message": "Plan and implement delegation."})
    delegation_runs = client.get("/v1/agent/delegation/runs")
    model_policy = client.get("/v1/agent/model-router/policy")
    model_route = client.post("/v1/agent/model-router/route", json={"role": "critic"})
    model_decisions = client.get("/v1/agent/model-router/decisions")
    failures = client.get("/v1/agent/self-repair/failures")
    promote_preview = client.post(
        "/v1/agent/self-repair/promote-preview",
        json={"failures": [{"failure_id": "failure-1", "failure_type": "tool_denied", "failed_role": "critic"}]},
    )
    review_queue = client.get("/v1/agent/review-queue")
    review_approve = client.post("/v1/agent/review-queue/review-1/approve")
    review_reject = client.post("/v1/agent/review-queue/review-1/reject")
    task_ledger_policy = client.get("/v1/agent/task-ledger/policy")
    task_ledger_plan = client.post("/v1/agent/task-ledger/plan", json={"message": "Plan task ledger handoff."})
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
    assert route.json()["plan"]["role"] == "critic"
    assert "write_text_artifact" in route.json()["plan"]["denied_tools"]
    assert memory_policy.json()["enabled"] is True
    assert memory_eval.json()["decision"]["status"] == "ready"
    assert tool_decisions.json()["count"] == 1
    assert memory_decisions.json()["count"] == 1
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
    assert "focus_agent_memory_conflict_count 1" in metrics.text
    assert "focus_agent_delegation_run_count 1" in metrics.text
    assert "focus_agent_review_pending_count 1" in metrics.text
    assert "focus_agent_task_ledger_task_count 1" in metrics.text
    assert "focus_agent_delegated_artifact_count 1" in metrics.text
