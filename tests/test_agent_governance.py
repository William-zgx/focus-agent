from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain.tools import tool

from focus_agent.api.main import create_app
from focus_agent.api.route_utils.agent_governance_trajectory_responses import (
    _agent_governance_metrics_from_turns,
    _plan_meta_governance_payload,
)
from focus_agent.capabilities.catalog import build_capability_registry, build_toolset_registry
from focus_agent.capabilities.tool_registry import ToolRegistry
from focus_agent.config import Settings
from focus_agent.core.branching import BranchRecord, BranchRole, BranchStatus
from focus_agent.core.governance import ContextMemoryEvidence, FeedbackEvent, SkillSelectionEvent
from focus_agent.core.request_context import RequestContext
from focus_agent.core.state import make_agent_state_record
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


def test_agent_feedback_trend_endpoint_summarizes_governance_signals() -> None:
    client, repository = _agent_governance_client()
    repository.save_feedback_event(
        FeedbackEvent(user_id="anonymous", source_kind="chat", sentiment="negative")
    )
    repository.save_feedback_event(
        FeedbackEvent(
            user_id="anonymous",
            source_kind="productivity_capture",
            sentiment="positive",
            category="note",
        )
    )
    repository.save_feedback_event(
        FeedbackEvent(user_id="someone-else", source_kind="chat", sentiment="negative")
    )
    repository.save_skill_selection_event(
        SkillSelectionEvent(
            user_id="anonymous",
            activated_skill_ids=["plan"],
            confidence=0.4,
            user_override={"removed": ["debug"]},
        )
    )
    repository.save_skill_selection_event(
        SkillSelectionEvent(user_id="anonymous", activated_skill_ids=["plan"], confidence=0.9)
    )
    repository.save_context_evidence(
        ContextMemoryEvidence(user_id="anonymous", drift_report={"drift_risk": "high"})
    )

    response = client.get("/v1/agent/feedback/trend")

    assert response.status_code == 200
    payload = response.json()
    assert payload["negative_feedback_count"] == 1
    assert payload["notes_tasks_capture_count"] == 1
    assert payload["context_high_drift_count"] == 1
    assert payload["skill_low_confidence_rate"] == 0.5
    assert payload["skill_override_rate"] == 0.5
    assert payload["top_failing_trajectory_samples"] == []
    assert payload["generated_at"]


def test_skill_selection_feedback_hides_missing_and_other_users_selections() -> None:
    client, repository = _agent_governance_client()
    other_user_selection_id = repository.save_skill_selection_event(
        SkillSelectionEvent(user_id="other-user")
    )

    for selection_id in (other_user_selection_id, "missing-selection"):
        response = client.post(
            f"/v1/agent/skills/selections/{selection_id}/feedback",
            json={"feedback": "useful"},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Skill selection not found."


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


def test_agent_skill_catalog_includes_capability_metadata(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "stocks"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """
---
name: stocks
description: Fetch read-only stock market data.
triggers: [stock:]
aliases: [股票, 股价, 行情]
localized_triggers: [股票:, 股票：]
domains: [finance, market-data]
intents: [quote lookup, 行情查询]
when_to_use: [Use when the user asks for market data]
primary_tools: [web_fetch]
recommended_tools: [web_search]
---
# Stocks
Use read-only market data.
""".strip()
        + "\n",
        encoding="utf-8",
    )
    client, _repository = _agent_governance_client()
    client.app.state.runtime.skill_registry = SkillRegistry([tmp_path / "skills"])

    catalog = client.get("/v1/agent/skills/catalog")

    assert catalog.status_code == 200
    stocks = next(item for item in catalog.json()["items"] if item["skill_id"] == "stocks")
    assert stocks["aliases"] == ["股票", "股价", "行情"]
    assert stocks["localized_triggers"] == ["股票:", "股票："]
    assert stocks["domains"] == ["finance", "market-data"]
    assert stocks["intents"] == ["quote lookup", "行情查询"]
    assert stocks["primary_tools"] == ["web_fetch"]


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
                        "memory_curator_decision",
                        {"promoted_memory_ids": ["record-memory"], "conflicts": []},
                        source="test",
                    )
                ],
                "memory_curator_decision": {
                    "promoted_memory_ids": ["legacy-memory"],
                    "conflicts": [{"candidate_id": "legacy-conflict"}],
                },
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

    assert _plan_meta_governance_payload(rows[0]["plan_meta"], "memory_curator_decision")[
        "promoted_memory_ids"
    ] == ["record-memory"]
    assert metrics["tool_intent_live_web_research"] == 1
    assert metrics["tool_intent_first_tool"] == 1
    assert metrics["memory_promotions"] == 2
    assert metrics["memory_conflicts"] == 1


def test_agent_governance_api_shapes(monkeypatch, tmp_path):
    _with_stub_frontend(monkeypatch, tmp_path)
    app = create_app()
    app.state.runtime = SimpleNamespace(
        settings=Settings(
            auth_enabled=False,
            agent_memory_curator_enabled=True,
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
    memory_policy = client.get("/v1/agent/memory/curator/policy")
    memory_eval = client.post(
        "/v1/agent/memory/curator/evaluate",
        json={
            "root_thread_id": "root-1",
            "branch_id": "branch-1",
            "findings": [{"finding": "Promote this branch finding."}],
        },
    )
    memory_decisions = client.get("/v1/agent/memory/curator/decisions")
    artifacts = client.get("/v1/agent/artifacts")
    metrics = client.get("/metrics")

    assert capabilities.status_code == 200
    assert capabilities.json()["count"] >= 3
    assert toolsets.status_code == 200
    assert any(item["name"] == "workspace" for item in toolsets.json()["items"])
    assert memory_policy.status_code == 200
    assert memory_policy.json()["enabled"] is True
    assert memory_eval.status_code == 200
    assert memory_eval.json()["decision"]["status"] == "ready"
    assert memory_decisions.status_code == 200
    assert memory_decisions.json()["count"] == 1
    assert memory_decisions.json()["items"][0]["conflicts"] == [{"candidate_id": "branch-1:0"}]
    assert artifacts.status_code == 200
    assert artifacts.json()["items"][0]["artifact_id"] == "artifact-1"
    assert metrics.status_code == 200
    assert "focus_agent_tool_intent_live_web_research_count 1" in metrics.text
    assert "focus_agent_tool_intent_first_tool_count 1" in metrics.text
    assert "focus_agent_memory_conflict_count 1" in metrics.text
    assert "focus_agent_delegated_artifact_count 1" in metrics.text
