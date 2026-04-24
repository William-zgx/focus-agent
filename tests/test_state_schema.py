import json

from focus_agent.core.types import (
    ArtifactRef,
    CitationRef,
    ConstraintItem,
    ContextBudget,
    FindingItem,
    PinnedFact,
    PromptMode,
)
from focus_agent.core.state import initial_agent_state, normalize_agent_state, serialize_agent_state


def test_initial_agent_state_populates_governance_defaults():
    state = initial_agent_state()

    assert state["rolling_summary"] == ""
    assert state["active_goal"] == ""
    assert state["prompt_mode"] == PromptMode.EXPLORE
    assert state["context_budget"] == ContextBudget()
    assert state["recent_messages"] == []
    assert state["pinned_facts"] == []
    assert state["user_constraints"] == []
    assert state["branch_local_findings"] == []
    assert state["imported_findings"] == []
    assert state["artifacts"] == []
    assert state["citations"] == []
    assert state["retrieved_memories"] == []
    assert state["memory_prompt_block"] == ""
    assert state["active_skill_ids"] == []
    assert state["available_skills_block"] == ""
    assert state["active_skills_block"] == ""
    assert state["role_route_plan"] is None
    assert state["memory_curator_decision"] is None
    assert state["tool_route_plan"] is None
    assert state["agent_delegation_plan"] is None
    assert state["agent_runs"] == []
    assert state["model_route_decision"] is None
    assert state["agent_failure_records"] == []
    assert state["agent_review_queue"] == []
    assert state["memory_write_requests"] == []
    assert state["memory_write_result"] == {}


def test_initial_agent_state_returns_fresh_mutable_collections():
    first = initial_agent_state()
    second = initial_agent_state()

    first["pinned_facts"].append(PinnedFact(fact="Remember the scope"))
    first["context_budget"].findings_limit = 3

    assert second["pinned_facts"] == []
    assert second["context_budget"].findings_limit == 8


def test_normalize_agent_state_backfills_new_fields_without_overwriting_existing_values():
    normalized = normalize_agent_state(
        {
            "rolling_summary": "Existing summary",
            "active_goal": "Finish the review",
            "pinned_items": ["legacy pin"],
            "llm_calls": 4,
        }
    )

    assert normalized["rolling_summary"] == "Existing summary"
    assert normalized["active_goal"] == "Finish the review"
    assert normalized["pinned_items"] == ["legacy pin"]
    assert normalized["llm_calls"] == 4
    assert normalized["pinned_facts"] == []
    assert normalized["imported_findings"] == []
    assert normalized["prompt_mode"] == PromptMode.EXPLORE
    assert normalized["retrieved_memories"] == []
    assert normalized["memory_prompt_block"] == ""
    assert normalized["active_skill_ids"] == []
    assert normalized["available_skills_block"] == ""
    assert normalized["active_skills_block"] == ""
    assert normalized["role_route_plan"] is None
    assert normalized["memory_curator_decision"] is None
    assert normalized["tool_route_plan"] is None
    assert normalized["agent_delegation_plan"] is None
    assert normalized["agent_runs"] == []
    assert normalized["model_route_decision"] is None
    assert normalized["agent_failure_records"] == []
    assert normalized["agent_review_queue"] == []
    assert normalized["memory_write_requests"] == []
    assert normalized["memory_write_result"] == {}


def test_serialize_agent_state_round_trips_structured_governance_models():
    state = normalize_agent_state(
        {
            "pinned_facts": [PinnedFact(fact="Use verified sources", source="user")],
            "user_constraints": [ConstraintItem(constraint="Keep answers concise")],
            "branch_local_findings": [
                FindingItem(
                    finding="Branch discovered a stable API boundary",
                    evidence_refs=["doc-1"],
                    confidence=0.8,
                    source_branch_id="branch-1",
                )
            ],
            "imported_findings": [
                FindingItem(
                    finding="Parent accepted the summary",
                    evidence_refs=["proposal-1"],
                )
            ],
            "artifacts": [
                ArtifactRef(
                    artifact_id="artifact-1",
                    title="Merge draft",
                    kind="markdown",
                    uri="file:///tmp/merge.md",
                )
            ],
            "citations": [
                CitationRef(
                    label="LangGraph docs",
                    uri="https://docs.langchain.com/",
                    quote="thread_id is the durable thread key",
                )
            ],
            "context_budget": ContextBudget(recent_message_limit=6, findings_limit=4),
            "prompt_mode": PromptMode.BRANCH_REVIEW,
            "retrieved_memories": [{"memory_id": "mem-1", "summary": "Approved branch insight"}],
            "memory_prompt_block": "## Retrieved long-term memories\n- Approved branch insight",
            "active_skill_ids": ["review"],
            "available_skills_block": "## Available skills\n- review",
            "active_skills_block": "## Active skills\n- review",
            "role_route_plan": {
                "enabled": True,
                "decisions": [{"role": "executor", "model_id": "openai:gpt-4.1-mini"}],
            },
            "memory_curator_decision": {"enabled": True, "status": "ready"},
            "tool_route_plan": {"enabled": True, "allowed_tools": ["search_code"]},
            "agent_delegation_plan": {"enabled": True, "tasks": [{"task_id": "task-1"}]},
            "agent_runs": [{"run_id": "run-1", "status": "completed"}],
            "model_route_decision": {"enabled": True, "effective_model": "openai:gpt-4.1-mini"},
            "agent_failure_records": [{"failure_type": "tool_denied"}],
            "agent_review_queue": [{"item_id": "review-1", "status": "pending"}],
            "memory_write_requests": [{"kind": "turn_summary", "summary": "Carry this forward"}],
            "memory_write_result": {"prepared": 1, "written": ["mem-1"]},
        }
    )

    payload = serialize_agent_state(state)
    encoded = json.dumps(payload, ensure_ascii=False)
    decoded = json.loads(encoded)

    assert decoded["pinned_facts"][0]["fact"] == "Use verified sources"
    assert decoded["user_constraints"][0]["constraint"] == "Keep answers concise"
    assert decoded["branch_local_findings"][0]["evidence_refs"] == ["doc-1"]
    assert decoded["artifacts"][0]["kind"] == "markdown"
    assert decoded["citations"][0]["label"] == "LangGraph docs"
    assert decoded["context_budget"]["recent_message_limit"] == 6
    assert decoded["prompt_mode"] == "branch_review"
    assert decoded["retrieved_memories"][0]["memory_id"] == "mem-1"
    assert decoded["memory_prompt_block"].startswith("## Retrieved long-term memories")
    assert decoded["active_skill_ids"] == ["review"]
    assert decoded["available_skills_block"].startswith("## Available skills")
    assert decoded["active_skills_block"].startswith("## Active skills")
    assert decoded["role_route_plan"]["decisions"][0]["role"] == "executor"
    assert decoded["memory_curator_decision"]["status"] == "ready"
    assert decoded["tool_route_plan"]["allowed_tools"] == ["search_code"]
    assert decoded["agent_delegation_plan"]["tasks"][0]["task_id"] == "task-1"
    assert decoded["agent_runs"][0]["run_id"] == "run-1"
    assert decoded["model_route_decision"]["effective_model"] == "openai:gpt-4.1-mini"
    assert decoded["agent_failure_records"][0]["failure_type"] == "tool_denied"
    assert decoded["agent_review_queue"][0]["status"] == "pending"
    assert decoded["memory_write_requests"][0]["kind"] == "turn_summary"
    assert decoded["memory_write_result"]["written"] == ["mem-1"]
