from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from focus_agent.core.state import (
    BRANCH_STATE_FIELDS,
    CONVERSATION_STATE_FIELDS,
    GOVERNANCE_STATE_FIELDS,
    MEMORY_STATE_FIELDS,
    OBSERVABILITY_STATE_FIELDS,
    AgentStateDomain,
    AgentStateKey,
    default_agent_state_slice,
    slice_agent_state,
)
from focus_agent.core.types import ContextBudget, PromptMode


class HarnessSchemaModel(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")


class ConversationStateSlice(HarnessSchemaModel):
    messages: list[Any] = Field(default_factory=list)
    task_brief: str = ""
    rolling_summary: str = ""
    recent_messages: list[Any] = Field(default_factory=list)
    pinned_facts: list[Any] = Field(default_factory=list)
    pinned_items: list[str] = Field(default_factory=list)
    user_constraints: list[Any] = Field(default_factory=list)
    active_goal: str = ""
    active_plan: list[str] = Field(default_factory=list)
    assembled_context: str = ""
    context_budget: ContextBudget = Field(default_factory=ContextBudget)
    prompt_mode: PromptMode = PromptMode.EXPLORE
    active_skill_ids: list[str] = Field(default_factory=list)
    available_skills_block: str = ""
    active_skills_block: str = ""


class BranchStateSlice(HarnessSchemaModel):
    branch_meta: dict[str, Any] | None = None
    branch_actions: list[Any] = Field(default_factory=list)
    branch_local_findings: list[Any] = Field(default_factory=list)
    imported_findings: list[Any] = Field(default_factory=list)
    merge_queue: list[dict[str, Any]] = Field(default_factory=list)
    merge_proposal: dict[str, Any] | None = None
    merge_decision: dict[str, Any] | None = None
    artifacts: list[Any] = Field(default_factory=list)
    citations: list[Any] = Field(default_factory=list)


class MemoryStateSlice(HarnessSchemaModel):
    rolling_summary: str = ""
    pinned_facts: list[Any] = Field(default_factory=list)
    pinned_items: list[str] = Field(default_factory=list)
    retrieved_memories: list[dict[str, Any]] = Field(default_factory=list)
    memory_prompt_block: str = ""
    memory_retrieval_plan: dict[str, Any] = Field(default_factory=dict)
    memory_write_requests: list[dict[str, Any]] = Field(default_factory=list)
    memory_write_result: dict[str, Any] = Field(default_factory=dict)


class GovernanceStateSlice(HarnessSchemaModel):
    context_budget: ContextBudget = Field(default_factory=ContextBudget)
    prompt_mode: PromptMode = PromptMode.EXPLORE
    selected_model: str = ""
    selected_thinking_mode: str = ""
    role_route_plan: dict[str, Any] | None = None
    governance_records: list[dict[str, Any]] = Field(default_factory=list)
    memory_curator_decision: dict[str, Any] | None = None
    tool_intent_plan: dict[str, Any] | None = None
    tool_route_plan: dict[str, Any] | None = None
    pending_tool_action: dict[str, Any] | None = None
    evidence_bundle: list[dict[str, Any]] = Field(default_factory=list)
    agent_delegation_plan: dict[str, Any] | None = None
    agent_runs: list[dict[str, Any]] = Field(default_factory=list)
    model_route_decision: dict[str, Any] | None = None
    agent_failure_records: list[dict[str, Any]] = Field(default_factory=list)
    agent_review_queue: list[dict[str, Any]] = Field(default_factory=list)
    context_budget_decision: dict[str, Any] | None = None
    context_compression_plan: dict[str, Any] | None = None
    context_artifact_refs: list[dict[str, Any]] = Field(default_factory=list)
    role_context_views: list[dict[str, Any]] = Field(default_factory=list)
    context_compaction: dict[str, Any] = Field(default_factory=dict)
    agent_task_ledger: dict[str, Any] | None = None
    delegated_artifacts: list[dict[str, Any]] = Field(default_factory=list)
    artifact_synthesis_result: dict[str, Any] | None = None
    critic_gate_result: dict[str, Any] | None = None
    memory_write_result: dict[str, Any] = Field(default_factory=dict)
    plan: Any = None
    current_step_id: str = ""
    reflection: Any = None


class ObservabilityStateSlice(HarnessSchemaModel):
    llm_calls: int = 0
    branch_action_audit: list[dict[str, Any]] = Field(default_factory=list)
    plan_meta: dict[str, Any] = Field(default_factory=dict)
    role_route_plan: dict[str, Any] | None = None
    governance_records: list[dict[str, Any]] = Field(default_factory=list)
    memory_curator_decision: dict[str, Any] | None = None
    tool_intent_plan: dict[str, Any] | None = None
    tool_route_plan: dict[str, Any] | None = None
    pending_tool_action: dict[str, Any] | None = None
    evidence_bundle: list[dict[str, Any]] = Field(default_factory=list)
    agent_delegation_plan: dict[str, Any] | None = None
    agent_runs: list[dict[str, Any]] = Field(default_factory=list)
    model_route_decision: dict[str, Any] | None = None
    agent_failure_records: list[dict[str, Any]] = Field(default_factory=list)
    agent_review_queue: list[dict[str, Any]] = Field(default_factory=list)
    context_budget_decision: dict[str, Any] | None = None
    context_compression_plan: dict[str, Any] | None = None
    context_artifact_refs: list[dict[str, Any]] = Field(default_factory=list)
    role_context_views: list[dict[str, Any]] = Field(default_factory=list)
    context_compaction: dict[str, Any] = Field(default_factory=dict)
    agent_task_ledger: dict[str, Any] | None = None
    delegated_artifacts: list[dict[str, Any]] = Field(default_factory=list)
    artifact_synthesis_result: dict[str, Any] | None = None
    critic_gate_result: dict[str, Any] | None = None
    memory_retrieval_plan: dict[str, Any] = Field(default_factory=dict)
    memory_write_result: dict[str, Any] = Field(default_factory=dict)


class AgentStateSlices(HarnessSchemaModel):
    conversation: ConversationStateSlice = Field(default_factory=ConversationStateSlice)
    branch: BranchStateSlice = Field(default_factory=BranchStateSlice)
    memory: MemoryStateSlice = Field(default_factory=MemoryStateSlice)
    governance: GovernanceStateSlice = Field(default_factory=GovernanceStateSlice)
    observability: ObservabilityStateSlice = Field(default_factory=ObservabilityStateSlice)

    @classmethod
    def from_state(cls, state: Mapping[str, Any] | None = None) -> AgentStateSlices:
        return build_state_slices(state)


@dataclass(frozen=True, slots=True)
class StateSliceSpec:
    domain: AgentStateDomain
    fields: tuple[AgentStateKey, ...]
    model: type[HarnessSchemaModel]


@dataclass(frozen=True, slots=True)
class StateSlice:
    domain: AgentStateDomain
    fields: tuple[AgentStateKey, ...]
    values: Mapping[str, Any]

    def to_model(self) -> HarnessSchemaModel:
        return STATE_SLICE_SPECS[self.domain].model.model_validate(dict(self.values))

    def to_dict(self, *, mode: str = "python") -> dict[str, Any]:
        return self.to_model().model_dump(mode=mode)


STATE_SLICE_SPECS: Mapping[AgentStateDomain, StateSliceSpec] = MappingProxyType(
    {
        "conversation": StateSliceSpec(
            domain="conversation",
            fields=CONVERSATION_STATE_FIELDS,
            model=ConversationStateSlice,
        ),
        "branch": StateSliceSpec(
            domain="branch",
            fields=BRANCH_STATE_FIELDS,
            model=BranchStateSlice,
        ),
        "memory": StateSliceSpec(
            domain="memory",
            fields=MEMORY_STATE_FIELDS,
            model=MemoryStateSlice,
        ),
        "governance": StateSliceSpec(
            domain="governance",
            fields=GOVERNANCE_STATE_FIELDS,
            model=GovernanceStateSlice,
        ),
        "observability": StateSliceSpec(
            domain="observability",
            fields=OBSERVABILITY_STATE_FIELDS,
            model=ObservabilityStateSlice,
        ),
    }
)


def state_slice_model(
    domain: AgentStateDomain,
    state: Mapping[str, Any] | None = None,
    *,
    include_defaults: bool = True,
) -> HarnessSchemaModel:
    spec = STATE_SLICE_SPECS[domain]
    values = (
        default_agent_state_slice(domain)
        if state is None and include_defaults
        else slice_agent_state(state, domain, include_defaults=include_defaults)
    )
    return spec.model.model_validate(values)


def state_slice_dict(
    domain: AgentStateDomain,
    state: Mapping[str, Any] | None = None,
    *,
    include_defaults: bool = True,
    mode: str = "python",
) -> dict[str, Any]:
    return state_slice_model(domain, state, include_defaults=include_defaults).model_dump(mode=mode)


def build_state_slices(state: Mapping[str, Any] | None = None) -> AgentStateSlices:
    return AgentStateSlices(
        conversation=state_slice_model("conversation", state),
        branch=state_slice_model("branch", state),
        memory=state_slice_model("memory", state),
        governance=state_slice_model("governance", state),
        observability=state_slice_model("observability", state),
    )


__all__ = [
    "AgentStateSlices",
    "BranchStateSlice",
    "ConversationStateSlice",
    "GovernanceStateSlice",
    "HarnessSchemaModel",
    "MemoryStateSlice",
    "ObservabilityStateSlice",
    "STATE_SLICE_SPECS",
    "StateSlice",
    "StateSliceSpec",
    "build_state_slices",
    "state_slice_dict",
    "state_slice_model",
]
