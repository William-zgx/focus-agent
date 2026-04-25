from __future__ import annotations

import operator
from typing import Annotated, Any, Mapping, TypedDict

from langchain.messages import AnyMessage
from pydantic import BaseModel

from .types import (
    ArtifactRef,
    CitationRef,
    ConstraintItem,
    ContextBudget,
    FindingItem,
    PinnedFact,
    Plan,
    PromptMode,
    ReflectionVerdict,
)


class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], operator.add]
    task_brief: str

    # Written by the graph after each turn summary pass, read by prompt assembly,
    # and safe to import into parent threads through an explicit merge review.
    rolling_summary: str

    # Written by turn preprocessing or context assembly as the clipped working set
    # for the current prompt, read by prompt assembly, and not directly merge-imported.
    recent_messages: list[AnyMessage]

    # Written by the user or explicit pin actions, read by prompt assembly,
    # and allowed to be merge-imported when intentionally selected.
    pinned_facts: Annotated[list[PinnedFact], operator.add]

    # Backward-compatible legacy pinned strings still read by the current prompt code.
    pinned_items: Annotated[list[str], operator.add]

    # Written by user intent extraction or planning steps, read by prompt assembly,
    # and safe to merge-import as part of a reviewed branch summary.
    user_constraints: Annotated[list[ConstraintItem], operator.add]

    # Written by user turns or planning nodes, read by prompt assembly,
    # and safe to merge-import when it remains the active parent goal.
    active_goal: str

    # Backward-compatible legacy plan lines kept until the new context policy lands.
    active_plan: Annotated[list[str], operator.add]

    # Written by context assembly, read only by the model invocation node,
    # and never merge-imported because it is a transient prompt artifact.
    assembled_context: str

    llm_calls: int
    branch_meta: dict[str, Any] | None

    # Written only by branch execution nodes, read by merge proposal generation,
    # and merge-importable after explicit review.
    branch_local_findings: Annotated[list[FindingItem], operator.add]

    # Written only when a reviewed branch import is applied to the parent thread,
    # read by prompt assembly, and already considered imported.
    imported_findings: Annotated[list[FindingItem], operator.add]

    # Backward-compatible imported branch payloads used by the current prompt code.
    merge_queue: Annotated[list[dict[str, Any]], operator.add]

    merge_proposal: dict[str, Any] | None
    merge_decision: dict[str, Any] | None

    # Written by tools or branch workflows, read by prompt assembly and merge review,
    # and merge-importable when explicitly selected.
    artifacts: Annotated[list[ArtifactRef], operator.add]

    # Written by retrieval or evidence-tracking steps, read by prompt assembly,
    # and merge-importable when attached to imported findings or artifacts.
    citations: Annotated[list[CitationRef], operator.add]

    # Written by system defaults or runtime policy, read by context assembly,
    # and not merge-imported because it is execution policy rather than content.
    context_budget: ContextBudget

    # Written by orchestration logic to describe how the next prompt should be built,
    # read by context assembly, and not merge-imported because it is ephemeral.
    prompt_mode: PromptMode

    # Written by memory retrieval nodes, read by context assembly and debugging APIs,
    # and never merge-imported because it is a transient retrieval snapshot.
    retrieved_memories: list[dict[str, Any]]

    # Written by prompt assembly after memory rendering, read by model invocation,
    # and never merge-imported because it only reflects the current prompt surface.
    memory_prompt_block: str

    # Written by skill selection for the active turn, read by prompt assembly,
    # and reused on resume when the turn is still in progress.
    active_skill_ids: list[str]

    # Written by prompt assembly from the registry and read only by the model node.
    available_skills_block: str
    active_skills_block: str

    # Written by the chat API for each turn so the runtime can switch providers/models per thread.
    selected_model: str
    selected_thinking_mode: str

    # Written when role routing v2 is enabled. By default this is observability
    # data; Delegation Runtime can consume it when its feature flag is enabled.
    role_route_plan: dict[str, Any] | None

    # Written by Memory Curator when branch-local memories are evaluated for
    # promotion. It is observability data unless merge auto-promotion is enabled.
    memory_curator_decision: dict[str, Any] | None

    # Written by Tool Router before model invocation. When enforcement is enabled
    # it also controls the tools bound to the model for this turn.
    tool_route_plan: dict[str, Any] | None

    # Written by Delegation Runtime when multi-agent role runs are planned or
    # enforced. It stays in plan_meta for observability and replay.
    agent_delegation_plan: dict[str, Any] | None
    agent_runs: list[dict[str, Any]]
    model_route_decision: dict[str, Any] | None
    agent_failure_records: list[dict[str, Any]]
    agent_review_queue: list[dict[str, Any]]

    # Written by Context Engineering v2 when enabled. These describe context
    # budget, compression, artifact references, and role-specific prompt views.
    context_budget_decision: dict[str, Any] | None
    context_compression_plan: dict[str, Any] | None
    context_artifact_refs: list[dict[str, Any]]
    role_context_views: list[dict[str, Any]]
    context_compaction: dict[str, Any]

    # Written by Task Ledger / Delegated Artifact Synthesis governance when
    # enabled. These are observability and synthesis artifacts for role runs.
    agent_task_ledger: dict[str, Any] | None
    delegated_artifacts: list[dict[str, Any]]
    artifact_synthesis_result: dict[str, Any] | None
    critic_gate_result: dict[str, Any] | None

    # Written by extraction nodes after a turn, read by persistence nodes,
    # and never merge-imported because it is a transient write queue.
    memory_write_requests: list[dict[str, Any]]
    memory_write_result: dict[str, Any]

    # Plan-Act-Reflect: written by `plan` node, read by `agent_loop` context and
    # `reflect` node. Not merge-imported: a plan belongs to the active turn.
    plan: Plan | None
    current_step_id: str
    reflection: ReflectionVerdict | None
    plan_meta: dict[str, Any]


def initial_agent_state() -> AgentState:
    return {
        "messages": [],
        "task_brief": "",
        "rolling_summary": "",
        "recent_messages": [],
        "pinned_facts": [],
        "pinned_items": [],
        "user_constraints": [],
        "active_goal": "",
        "active_plan": [],
        "assembled_context": "",
        "llm_calls": 0,
        "branch_meta": None,
        "branch_local_findings": [],
        "imported_findings": [],
        "merge_queue": [],
        "merge_proposal": None,
        "merge_decision": None,
        "artifacts": [],
        "citations": [],
        "context_budget": ContextBudget(),
        "prompt_mode": PromptMode.EXPLORE,
        "retrieved_memories": [],
        "memory_prompt_block": "",
        "active_skill_ids": [],
        "available_skills_block": "",
        "active_skills_block": "",
        "selected_model": "",
        "selected_thinking_mode": "",
        "role_route_plan": None,
        "memory_curator_decision": None,
        "tool_route_plan": None,
        "agent_delegation_plan": None,
        "agent_runs": [],
        "model_route_decision": None,
        "agent_failure_records": [],
        "agent_review_queue": [],
        "context_budget_decision": None,
        "context_compression_plan": None,
        "context_artifact_refs": [],
        "role_context_views": [],
        "context_compaction": {},
        "agent_task_ledger": None,
        "delegated_artifacts": [],
        "artifact_synthesis_result": None,
        "critic_gate_result": None,
        "memory_write_requests": [],
        "memory_write_result": {},
        "plan": None,
        "current_step_id": "",
        "reflection": None,
        "plan_meta": {},
    }


def normalize_agent_state(state: Mapping[str, Any] | None = None) -> AgentState:
    normalized = initial_agent_state()
    if state:
        normalized.update(dict(state))
    return normalized


def serialize_agent_state(state: Mapping[str, Any]) -> dict[str, Any]:
    return {key: _serialize_value(value) for key, value in dict(state).items()}


def _serialize_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize_value(item) for key, item in value.items()}
    return value
