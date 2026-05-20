from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal, TypeAlias

from . import state_governance_metrics as _governance_metrics
from .state_governance_metrics import (
    agent_delegation_metrics,
    agent_failure_metrics,
    agent_review_metrics,
    agent_task_ledger_metrics,
    answer_verification_metrics,
    context_artifact_ref_metrics,
    context_budget_metrics,
    critic_gate_metrics,
    delegated_artifact_metrics,
    execution_contract_metrics,
    memory_curator_metrics,
    memory_write_metrics,
    model_route_metrics,
    tool_intent_metrics,
    tool_route_metrics,
)

GOVERNANCE_METRIC_KEYS = _governance_metrics.GOVERNANCE_METRIC_KEYS

AgentStateKey: TypeAlias = Literal[
    "messages",
    "task_brief",
    "rolling_summary",
    "recent_messages",
    "pinned_facts",
    "pinned_items",
    "user_constraints",
    "active_goal",
    "active_plan",
    "assembled_context",
    "llm_calls",
    "branch_meta",
    "branch_actions",
    "branch_action_audit",
    "branch_local_findings",
    "imported_findings",
    "merge_queue",
    "merge_proposal",
    "merge_decision",
    "artifacts",
    "citations",
    "context_budget",
    "prompt_mode",
    "retrieved_memories",
    "memory_prompt_block",
    "memory_retrieval_plan",
    "active_skill_ids",
    "available_skills_block",
    "active_skills_block",
    "selected_model",
    "selected_thinking_mode",
    "role_route_plan",
    "governance_records",
    "memory_curator_decision",
    "tool_intent_plan",
    "tool_route_plan",
    "pending_tool_action",
    "evidence_bundle",
    "evidence_ledger",
    "execution_contract",
    "answer_verification",
    "agent_delegation_plan",
    "agent_runs",
    "model_route_decision",
    "agent_failure_records",
    "agent_review_queue",
    "context_budget_decision",
    "context_compression_plan",
    "context_artifact_refs",
    "role_context_views",
    "context_compaction",
    "agent_task_ledger",
    "delegated_artifacts",
    "artifact_synthesis_result",
    "critic_gate_result",
    "memory_write_requests",
    "memory_write_result",
    "plan",
    "current_step_id",
    "reflection",
    "plan_meta",
]
AgentStateDomain: TypeAlias = Literal[
    "conversation",
    "branch",
    "memory",
    "governance",
    "observability",
]
AgentStateRecordDomain: TypeAlias = Literal["governance", "observability"]
AgentStateRecordName: TypeAlias = Literal[
    "role_route_plan",
    "memory_curator_decision",
    "tool_route_plan",
    "tool_intent_plan",
    "agent_delegation_plan",
    "agent_runs",
    "model_route_decision",
    "agent_failure_records",
    "agent_review_queue",
    "context_budget_decision",
    "context_compression_plan",
    "context_artifact_refs",
    "role_context_views",
    "context_compaction",
    "agent_task_ledger",
    "delegated_artifacts",
    "artifact_synthesis_result",
    "critic_gate_result",
    "execution_contract",
    "answer_verification",
    "memory_write_result",
]

GOVERNANCE_RECORD_SCHEMA_VERSION = 2

GovernanceMetricExtractor: TypeAlias = Callable[[Any], Mapping[str, int]]


@dataclass(frozen=True, slots=True)
class GovernanceRecordDescriptor:
    name: AgentStateRecordName
    domain: AgentStateRecordDomain = "governance"
    mirror_key: AgentStateKey | None = None
    plan_meta_key: str | None = None
    metric_extractor: GovernanceMetricExtractor | None = None

    @property
    def projected_plan_meta_key(self) -> str:
        return self.plan_meta_key or str(self.mirror_key or self.name)


GOVERNANCE_RECORD_DESCRIPTORS: tuple[GovernanceRecordDescriptor, ...] = (
    GovernanceRecordDescriptor("role_route_plan", mirror_key="role_route_plan"),
    GovernanceRecordDescriptor(
        "memory_curator_decision",
        mirror_key="memory_curator_decision",
        metric_extractor=memory_curator_metrics,
    ),
    GovernanceRecordDescriptor(
        "tool_intent_plan",
        mirror_key="tool_intent_plan",
        metric_extractor=tool_intent_metrics,
    ),
    GovernanceRecordDescriptor(
        "tool_route_plan",
        mirror_key="tool_route_plan",
        metric_extractor=tool_route_metrics,
    ),
    GovernanceRecordDescriptor(
        "memory_write_result",
        domain="observability",
        mirror_key="memory_write_result",
        metric_extractor=memory_write_metrics,
    ),
    GovernanceRecordDescriptor(
        "execution_contract",
        domain="observability",
        mirror_key="execution_contract",
        metric_extractor=execution_contract_metrics,
    ),
    GovernanceRecordDescriptor(
        "answer_verification",
        domain="observability",
        mirror_key="answer_verification",
        metric_extractor=answer_verification_metrics,
    ),
    GovernanceRecordDescriptor(
        "agent_delegation_plan",
        mirror_key="agent_delegation_plan",
        metric_extractor=agent_delegation_metrics,
    ),
    GovernanceRecordDescriptor("agent_runs", mirror_key="agent_runs"),
    GovernanceRecordDescriptor(
        "model_route_decision",
        mirror_key="model_route_decision",
        metric_extractor=model_route_metrics,
    ),
    GovernanceRecordDescriptor(
        "agent_failure_records",
        mirror_key="agent_failure_records",
        metric_extractor=agent_failure_metrics,
    ),
    GovernanceRecordDescriptor(
        "agent_review_queue",
        mirror_key="agent_review_queue",
        metric_extractor=agent_review_metrics,
    ),
    GovernanceRecordDescriptor(
        "context_budget_decision",
        mirror_key="context_budget_decision",
        metric_extractor=context_budget_metrics,
    ),
    GovernanceRecordDescriptor("context_compression_plan", mirror_key="context_compression_plan"),
    GovernanceRecordDescriptor(
        "context_artifact_refs",
        mirror_key="context_artifact_refs",
        metric_extractor=context_artifact_ref_metrics,
    ),
    GovernanceRecordDescriptor("role_context_views", mirror_key="role_context_views"),
    GovernanceRecordDescriptor("context_compaction", mirror_key="context_compaction"),
    GovernanceRecordDescriptor(
        "agent_task_ledger",
        mirror_key="agent_task_ledger",
        metric_extractor=agent_task_ledger_metrics,
    ),
    GovernanceRecordDescriptor(
        "delegated_artifacts",
        mirror_key="delegated_artifacts",
        metric_extractor=delegated_artifact_metrics,
    ),
    GovernanceRecordDescriptor("artifact_synthesis_result", mirror_key="artifact_synthesis_result"),
    GovernanceRecordDescriptor(
        "critic_gate_result",
        mirror_key="critic_gate_result",
        metric_extractor=critic_gate_metrics,
    ),
)
GOVERNANCE_RECORD_DESCRIPTOR_REGISTRY: Mapping[str, GovernanceRecordDescriptor] = MappingProxyType(
    {descriptor.name: descriptor for descriptor in GOVERNANCE_RECORD_DESCRIPTORS}
)
GOVERNANCE_RECORD_DESCRIPTORS_BY_MIRROR_KEY: Mapping[str, GovernanceRecordDescriptor] = (
    MappingProxyType(
        {
            str(descriptor.mirror_key): descriptor
            for descriptor in GOVERNANCE_RECORD_DESCRIPTORS
            if descriptor.mirror_key
        }
    )
)
GOVERNANCE_RECORD_MIRROR_KEYS: Mapping[str, AgentStateKey] = MappingProxyType(
    {
        descriptor.name: descriptor.mirror_key
        for descriptor in GOVERNANCE_RECORD_DESCRIPTORS
        if descriptor.mirror_key
    }
)

ALL_AGENT_STATE_FIELDS: tuple[AgentStateKey, ...] = (
    "messages",
    "task_brief",
    "rolling_summary",
    "recent_messages",
    "pinned_facts",
    "pinned_items",
    "user_constraints",
    "active_goal",
    "active_plan",
    "assembled_context",
    "llm_calls",
    "branch_meta",
    "branch_actions",
    "branch_action_audit",
    "branch_local_findings",
    "imported_findings",
    "merge_queue",
    "merge_proposal",
    "merge_decision",
    "artifacts",
    "citations",
    "context_budget",
    "prompt_mode",
    "retrieved_memories",
    "memory_prompt_block",
    "memory_retrieval_plan",
    "active_skill_ids",
    "available_skills_block",
    "active_skills_block",
    "selected_model",
    "selected_thinking_mode",
    "role_route_plan",
    "governance_records",
    "memory_curator_decision",
    "tool_intent_plan",
    "tool_route_plan",
    "pending_tool_action",
    "evidence_bundle",
    "evidence_ledger",
    "execution_contract",
    "answer_verification",
    "agent_delegation_plan",
    "agent_runs",
    "model_route_decision",
    "agent_failure_records",
    "agent_review_queue",
    "context_budget_decision",
    "context_compression_plan",
    "context_artifact_refs",
    "role_context_views",
    "context_compaction",
    "agent_task_ledger",
    "delegated_artifacts",
    "artifact_synthesis_result",
    "critic_gate_result",
    "memory_write_requests",
    "memory_write_result",
    "plan",
    "current_step_id",
    "reflection",
    "plan_meta",
)

# Domain slices are compatibility helpers only; they intentionally mirror the
# existing LangGraph wire keys rather than introducing nested persisted state.
CONVERSATION_STATE_FIELDS: tuple[AgentStateKey, ...] = (
    "messages",
    "task_brief",
    "rolling_summary",
    "recent_messages",
    "pinned_facts",
    "pinned_items",
    "user_constraints",
    "active_goal",
    "active_plan",
    "assembled_context",
    "context_budget",
    "prompt_mode",
    "active_skill_ids",
    "available_skills_block",
    "active_skills_block",
)
BRANCH_STATE_FIELDS: tuple[AgentStateKey, ...] = (
    "branch_meta",
    "branch_actions",
    "branch_local_findings",
    "imported_findings",
    "merge_queue",
    "merge_proposal",
    "merge_decision",
    "artifacts",
    "citations",
)
MEMORY_STATE_FIELDS: tuple[AgentStateKey, ...] = (
    "rolling_summary",
    "pinned_facts",
    "pinned_items",
    "retrieved_memories",
    "memory_prompt_block",
    "memory_retrieval_plan",
    "memory_write_requests",
    "memory_write_result",
)
GOVERNANCE_STATE_FIELDS: tuple[AgentStateKey, ...] = (
    "context_budget",
    "prompt_mode",
    "selected_model",
    "selected_thinking_mode",
    "role_route_plan",
    "governance_records",
    "memory_curator_decision",
    "tool_intent_plan",
    "tool_route_plan",
    "pending_tool_action",
    "evidence_bundle",
    "evidence_ledger",
    "execution_contract",
    "answer_verification",
    "agent_delegation_plan",
    "agent_runs",
    "model_route_decision",
    "agent_failure_records",
    "agent_review_queue",
    "context_budget_decision",
    "context_compression_plan",
    "context_artifact_refs",
    "role_context_views",
    "context_compaction",
    "agent_task_ledger",
    "delegated_artifacts",
    "artifact_synthesis_result",
    "critic_gate_result",
    "memory_write_result",
    "plan",
    "current_step_id",
    "reflection",
)
GOVERNANCE_TOP_LEVEL_FIELD_ALLOWLIST: frozenset[AgentStateKey] = frozenset(
    {
        "context_budget",
        "prompt_mode",
        "selected_model",
        "selected_thinking_mode",
        "role_route_plan",
        "governance_records",
        "memory_curator_decision",
        "tool_intent_plan",
        "tool_route_plan",
        "pending_tool_action",
        "evidence_bundle",
        "evidence_ledger",
        "execution_contract",
        "answer_verification",
        "agent_delegation_plan",
        "agent_runs",
        "model_route_decision",
        "agent_failure_records",
        "agent_review_queue",
        "context_budget_decision",
        "context_compression_plan",
        "context_artifact_refs",
        "role_context_views",
        "context_compaction",
        "agent_task_ledger",
        "delegated_artifacts",
        "artifact_synthesis_result",
        "critic_gate_result",
        "memory_write_result",
        "plan",
        "current_step_id",
        "reflection",
    }
)
OBSERVABILITY_STATE_FIELDS: tuple[AgentStateKey, ...] = (
    "llm_calls",
    "branch_action_audit",
    "plan_meta",
    "role_route_plan",
    "governance_records",
    "memory_curator_decision",
    "tool_intent_plan",
    "tool_route_plan",
    "pending_tool_action",
    "evidence_bundle",
    "evidence_ledger",
    "execution_contract",
    "answer_verification",
    "agent_delegation_plan",
    "agent_runs",
    "model_route_decision",
    "agent_failure_records",
    "agent_review_queue",
    "context_budget_decision",
    "context_compression_plan",
    "context_artifact_refs",
    "role_context_views",
    "context_compaction",
    "agent_task_ledger",
    "delegated_artifacts",
    "artifact_synthesis_result",
    "critic_gate_result",
    "memory_retrieval_plan",
    "memory_write_result",
)
STATE_DOMAIN_FIELDS: Mapping[AgentStateDomain, tuple[AgentStateKey, ...]] = MappingProxyType(
    {
        "conversation": CONVERSATION_STATE_FIELDS,
        "branch": BRANCH_STATE_FIELDS,
        "memory": MEMORY_STATE_FIELDS,
        "governance": GOVERNANCE_STATE_FIELDS,
        "observability": OBSERVABILITY_STATE_FIELDS,
    }
)
