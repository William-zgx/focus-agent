from __future__ import annotations

import operator
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Annotated, Any, Callable, Literal, Mapping, TypeAlias, TypedDict

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
    branch_actions: list[dict[str, Any]]
    branch_action_audit: list[dict[str, Any]]

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
    memory_retrieval_plan: dict[str, Any]

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

    # Append-only governance/observability records. New governance capabilities
    # should write records here and mirror legacy keys for current consumers.
    governance_records: Annotated[list[AgentStateRecord], operator.add]

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
    "tool_route_plan",
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
]


class AgentStateRecord(TypedDict, total=False):
    schema_version: int
    record_id: str
    created_at: str
    request_id: str | None
    actor: str
    domain: AgentStateRecordDomain
    name: AgentStateRecordName | str
    source: str
    mirror_key: AgentStateKey | str
    payload: Any
    metadata: dict[str, Any]


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


GOVERNANCE_METRIC_KEYS: tuple[str, ...] = (
    "memory_promotions",
    "memory_conflicts",
    "tool_router_denied",
    "tool_router_enforced",
    "agent_delegation_runs",
    "critic_rejects",
    "agent_review_pending",
    "model_router_fallback",
    "agent_failures",
    "context_artifact_refs",
    "context_over_budget",
    "agent_task_ledger_tasks",
    "delegated_artifacts",
    "critic_gate_rejected",
)


def _memory_curator_metrics(payload: Any) -> Mapping[str, int]:
    if not isinstance(payload, Mapping):
        return {}
    return {
        "memory_promotions": len(payload.get("promoted_memory_ids") or []),
        "memory_conflicts": len(payload.get("conflicts") or []),
    }


def _tool_route_metrics(payload: Any) -> Mapping[str, int]:
    if not isinstance(payload, Mapping):
        return {}
    return {
        "tool_router_denied": len(payload.get("denied_tools") or []),
        "tool_router_enforced": 1 if payload.get("enforce") else 0,
    }


def _agent_delegation_metrics(payload: Any) -> Mapping[str, int]:
    if not isinstance(payload, Mapping):
        return {}
    return {"agent_delegation_runs": len(payload.get("runs") or [])}


def _model_route_metrics(payload: Any) -> Mapping[str, int]:
    if not isinstance(payload, Mapping):
        return {}
    return {"model_router_fallback": 1 if payload.get("fallback_used") else 0}


def _agent_failure_metrics(payload: Any) -> Mapping[str, int]:
    if not isinstance(payload, list):
        return {}
    return {
        "agent_failures": len(payload),
        "critic_rejects": len(
            [
                item
                for item in payload
                if isinstance(item, Mapping) and item.get("failure_type") == "critic_rejected"
            ]
        ),
    }


def _agent_review_metrics(payload: Any) -> Mapping[str, int]:
    if not isinstance(payload, list):
        return {}
    return {
        "agent_review_pending": len(
            [item for item in payload if isinstance(item, Mapping) and item.get("status") == "pending"]
        )
    }


def _context_artifact_ref_metrics(payload: Any) -> Mapping[str, int]:
    if not isinstance(payload, list):
        return {}
    return {"context_artifact_refs": len(payload)}


def _context_budget_metrics(payload: Any) -> Mapping[str, int]:
    if not isinstance(payload, Mapping):
        return {}
    return {"context_over_budget": 1 if int(payload.get("over_budget_chars") or 0) > 0 else 0}


def _agent_task_ledger_metrics(payload: Any) -> Mapping[str, int]:
    if not isinstance(payload, Mapping):
        return {}
    return {"agent_task_ledger_tasks": len(payload.get("tasks") or [])}


def _delegated_artifact_metrics(payload: Any) -> Mapping[str, int]:
    if not isinstance(payload, list):
        return {}
    return {"delegated_artifacts": len(payload)}


def _critic_gate_metrics(payload: Any) -> Mapping[str, int]:
    if not isinstance(payload, Mapping):
        return {}
    return {"critic_gate_rejected": len(payload.get("rejected_artifact_ids") or [])}


GOVERNANCE_RECORD_DESCRIPTORS: tuple[GovernanceRecordDescriptor, ...] = (
    GovernanceRecordDescriptor("role_route_plan", mirror_key="role_route_plan"),
    GovernanceRecordDescriptor(
        "memory_curator_decision",
        mirror_key="memory_curator_decision",
        metric_extractor=_memory_curator_metrics,
    ),
    GovernanceRecordDescriptor(
        "tool_route_plan",
        mirror_key="tool_route_plan",
        metric_extractor=_tool_route_metrics,
    ),
    GovernanceRecordDescriptor(
        "agent_delegation_plan",
        mirror_key="agent_delegation_plan",
        metric_extractor=_agent_delegation_metrics,
    ),
    GovernanceRecordDescriptor("agent_runs", mirror_key="agent_runs"),
    GovernanceRecordDescriptor(
        "model_route_decision",
        mirror_key="model_route_decision",
        metric_extractor=_model_route_metrics,
    ),
    GovernanceRecordDescriptor(
        "agent_failure_records",
        mirror_key="agent_failure_records",
        metric_extractor=_agent_failure_metrics,
    ),
    GovernanceRecordDescriptor(
        "agent_review_queue",
        mirror_key="agent_review_queue",
        metric_extractor=_agent_review_metrics,
    ),
    GovernanceRecordDescriptor(
        "context_budget_decision",
        mirror_key="context_budget_decision",
        metric_extractor=_context_budget_metrics,
    ),
    GovernanceRecordDescriptor("context_compression_plan", mirror_key="context_compression_plan"),
    GovernanceRecordDescriptor(
        "context_artifact_refs",
        mirror_key="context_artifact_refs",
        metric_extractor=_context_artifact_ref_metrics,
    ),
    GovernanceRecordDescriptor("role_context_views", mirror_key="role_context_views"),
    GovernanceRecordDescriptor("context_compaction", mirror_key="context_compaction"),
    GovernanceRecordDescriptor(
        "agent_task_ledger",
        mirror_key="agent_task_ledger",
        metric_extractor=_agent_task_ledger_metrics,
    ),
    GovernanceRecordDescriptor(
        "delegated_artifacts",
        mirror_key="delegated_artifacts",
        metric_extractor=_delegated_artifact_metrics,
    ),
    GovernanceRecordDescriptor("artifact_synthesis_result", mirror_key="artifact_synthesis_result"),
    GovernanceRecordDescriptor(
        "critic_gate_result",
        mirror_key="critic_gate_result",
        metric_extractor=_critic_gate_metrics,
    ),
)
GOVERNANCE_RECORD_DESCRIPTOR_REGISTRY: Mapping[str, GovernanceRecordDescriptor] = MappingProxyType(
    {descriptor.name: descriptor for descriptor in GOVERNANCE_RECORD_DESCRIPTORS}
)
GOVERNANCE_RECORD_DESCRIPTORS_BY_MIRROR_KEY: Mapping[str, GovernanceRecordDescriptor] = MappingProxyType(
    {
        str(descriptor.mirror_key): descriptor
        for descriptor in GOVERNANCE_RECORD_DESCRIPTORS
        if descriptor.mirror_key
    }
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
    "tool_route_plan",
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
    "tool_route_plan",
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
        "tool_route_plan",
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
    "tool_route_plan",
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
        "branch_actions": [],
        "branch_action_audit": [],
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
        "memory_retrieval_plan": {},
        "active_skill_ids": [],
        "available_skills_block": "",
        "active_skills_block": "",
        "selected_model": "",
        "selected_thinking_mode": "",
        "role_route_plan": None,
        "governance_records": [],
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
    _apply_governance_record_mirrors(normalized)
    return normalized


def state_domain_fields(domain: AgentStateDomain) -> tuple[AgentStateKey, ...]:
    return STATE_DOMAIN_FIELDS[domain]


def state_domains_for_field(field: AgentStateKey) -> tuple[AgentStateDomain, ...]:
    return tuple(
        domain for domain, fields in STATE_DOMAIN_FIELDS.items() if field in fields
    )


def slice_agent_state(
    state: Mapping[str, Any] | None,
    domain: AgentStateDomain,
    *,
    include_defaults: bool = True,
) -> dict[AgentStateKey, Any]:
    source = normalize_agent_state(state) if include_defaults else dict(state or {})
    return {field: source[field] for field in state_domain_fields(domain) if field in source}


def default_agent_state_slice(domain: AgentStateDomain) -> dict[AgentStateKey, Any]:
    return slice_agent_state(None, domain)


def serialize_agent_state(state: Mapping[str, Any]) -> dict[str, Any]:
    serializable = with_agent_state_record_mirrors(state)
    return {key: _serialize_value(value) for key, value in serializable.items()}


_GOVERNANCE_MISSING = object()


def governance_record_descriptor(name_or_mirror_key: AgentStateRecordName | str) -> GovernanceRecordDescriptor | None:
    key = str(name_or_mirror_key)
    return GOVERNANCE_RECORD_DESCRIPTOR_REGISTRY.get(key) or GOVERNANCE_RECORD_DESCRIPTORS_BY_MIRROR_KEY.get(key)


def governance_metric_defaults() -> dict[str, int]:
    return {key: 0 for key in GOVERNANCE_METRIC_KEYS}


def governance_plan_meta_projection(state: Mapping[str, Any]) -> dict[str, Any]:
    projection: dict[str, Any] = {}
    governance_records = state.get("governance_records")
    if governance_records:
        projection["governance_records"] = _serialize_value(governance_records)
    for descriptor in GOVERNANCE_RECORD_DESCRIPTORS:
        payload = latest_agent_state_record_payload(
            state,
            descriptor.name,
            domain=descriptor.domain,
            default=_GOVERNANCE_MISSING,
        )
        if payload is _GOVERNANCE_MISSING or not _has_governance_projection_payload(payload):
            continue
        projection[descriptor.projected_plan_meta_key] = _serialize_value(payload)
    return projection


def governance_plan_meta_payload(
    plan_meta: Mapping[str, Any],
    key_path: AgentStateRecordName | str,
    *,
    default: Any = None,
) -> Any:
    parts = str(key_path).split(".")
    base_key = parts[0]
    descriptor = governance_record_descriptor(base_key)
    payload = latest_agent_state_record_payload(
        plan_meta,
        descriptor.name if descriptor else base_key,
        domain=descriptor.domain if descriptor else None,
        default=_GOVERNANCE_MISSING,
    )
    if payload is _GOVERNANCE_MISSING:
        payload = plan_meta.get(base_key, _GOVERNANCE_MISSING)
    if payload is _GOVERNANCE_MISSING:
        return default
    for part in parts[1:]:
        payload = payload.get(part) if isinstance(payload, Mapping) else _GOVERNANCE_MISSING
        if payload is _GOVERNANCE_MISSING:
            return default
    return payload


def governance_metrics_from_record_payloads(
    state: Mapping[str, Any],
    *,
    include_zero: bool = True,
) -> dict[str, int]:
    metrics = governance_metric_defaults() if include_zero else {}
    for descriptor in GOVERNANCE_RECORD_DESCRIPTORS:
        if descriptor.metric_extractor is None:
            continue
        payload = latest_agent_state_record_payload(
            state,
            descriptor.name,
            domain=descriptor.domain,
            default=_GOVERNANCE_MISSING,
        )
        if payload is _GOVERNANCE_MISSING or not _has_governance_projection_payload(payload):
            continue
        for key, value in descriptor.metric_extractor(payload).items():
            metric_value = int(value or 0)
            if include_zero or metric_value:
                metrics[key] = metrics.get(key, 0) + metric_value
    return metrics


def _has_governance_projection_payload(payload: Any) -> bool:
    if payload is None:
        return False
    if isinstance(payload, (list, tuple, dict)) and not payload:
        return False
    return True


def make_agent_state_record(
    name: AgentStateRecordName | str,
    payload: Any,
    *,
    source: str,
    domain: AgentStateRecordDomain = "governance",
    mirror_key: AgentStateKey | str | None = None,
    metadata: Mapping[str, Any] | None = None,
    request_id: str | None = None,
    actor: str | None = None,
    created_at: datetime | str | None = None,
) -> AgentStateRecord:
    descriptor = governance_record_descriptor(name)
    resolved_mirror_key = descriptor.mirror_key if descriptor and domain == descriptor.domain else None
    record: AgentStateRecord = {
        "schema_version": GOVERNANCE_RECORD_SCHEMA_VERSION,
        "record_id": f"{source}:{domain}:{name}",
        "created_at": _record_created_at(created_at),
        "request_id": request_id,
        "actor": actor or source,
        "domain": domain,
        "name": name,
        "source": source,
        "payload": _serialize_value(payload),
    }
    if resolved_mirror_key:
        record["mirror_key"] = resolved_mirror_key
    if metadata:
        record["metadata"] = dict(metadata)
    return record


def append_agent_state_record(
    updates: dict[str, Any],
    name: AgentStateRecordName | str,
    payload: Any,
    *,
    source: str,
    domain: AgentStateRecordDomain = "governance",
    mirror_key: AgentStateKey | str | None = None,
    metadata: Mapping[str, Any] | None = None,
    request_id: str | None = None,
    actor: str | None = None,
) -> AgentStateRecord:
    record = make_agent_state_record(
        name,
        payload,
        source=source,
        domain=domain,
        mirror_key=mirror_key,
        metadata=metadata,
        request_id=request_id,
        actor=actor,
    )
    updates.setdefault("governance_records", []).append(record)
    resolved_mirror_key = record.get("mirror_key")
    if resolved_mirror_key in ALL_AGENT_STATE_FIELDS:
        updates[resolved_mirror_key] = payload
    return record


def with_agent_state_record_mirrors(state: Mapping[str, Any]) -> dict[str, Any]:
    mirrored = dict(state)
    _apply_governance_record_mirrors(mirrored)
    return mirrored


def agent_state_record_payloads(
    state: Mapping[str, Any],
    name_or_mirror_key: AgentStateRecordName | str,
    *,
    domain: AgentStateRecordDomain | None = None,
) -> list[Any]:
    records = state.get("governance_records") or []
    if not isinstance(records, list):
        return []
    return [
        record.get("payload")
        for record in records
        if isinstance(record, Mapping)
        and _agent_state_record_matches(record, name_or_mirror_key, domain=domain)
    ]


def latest_agent_state_record_payload(
    state: Mapping[str, Any],
    name_or_mirror_key: AgentStateRecordName | str,
    *,
    domain: AgentStateRecordDomain | None = None,
    default: Any = None,
) -> Any:
    records = state.get("governance_records") or []
    if isinstance(records, list):
        for record in reversed(records):
            if not isinstance(record, Mapping):
                continue
            if _agent_state_record_matches(record, name_or_mirror_key, domain=domain):
                return record.get("payload")

    legacy_key = _legacy_mirror_key_for(name_or_mirror_key)
    if legacy_key in state:
        return state.get(legacy_key)
    return default


def _apply_governance_record_mirrors(state: dict[str, Any]) -> None:
    records = state.get("governance_records") or []
    if not isinstance(records, list):
        return
    for record in records:
        if not isinstance(record, Mapping):
            continue
        mirror_key = _agent_state_record_mirror_key(record)
        if mirror_key not in ALL_AGENT_STATE_FIELDS:
            continue
        state[mirror_key] = record.get("payload")


def _agent_state_record_matches(
    record: Mapping[str, Any],
    name_or_mirror_key: AgentStateRecordName | str,
    *,
    domain: AgentStateRecordDomain | None,
) -> bool:
    record_domain = record.get("domain")
    if domain is not None and record_domain not in (None, domain):
        return False
    expected = str(name_or_mirror_key)
    record_name = str(record.get("name") or "")
    return expected == record_name or expected == _agent_state_record_mirror_key(record)


def _agent_state_record_mirror_key(record: Mapping[str, Any]) -> str:
    record_name = str(record.get("name") or "")
    descriptor = governance_record_descriptor(record_name)
    if descriptor is None and not record_name:
        descriptor = governance_record_descriptor(str(record.get("mirror_key") or ""))
    if descriptor is None:
        return ""
    record_domain = record.get("domain")
    if record_domain not in (None, descriptor.domain):
        return ""
    return str(descriptor.mirror_key or "")


def _legacy_mirror_key_for(name_or_mirror_key: AgentStateRecordName | str) -> str:
    descriptor = governance_record_descriptor(name_or_mirror_key)
    return str(descriptor.mirror_key if descriptor and descriptor.mirror_key else name_or_mirror_key)


def _record_created_at(value: datetime | str | None) -> str:
    if isinstance(value, datetime):
        timestamp = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return timestamp.astimezone(timezone.utc).isoformat()
    if value:
        return str(value)
    return datetime.now(timezone.utc).isoformat()


def _serialize_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize_value(item) for key, item in value.items()}
    return value
