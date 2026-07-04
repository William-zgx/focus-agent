"""State field categorization for AgentState.

Inspired by pi/opencode's distinction between durable conversation state,
per-turn working state, and append-only observability records. This module
partitions AgentState fields into three lifecycles so persistence layers,
checkpointers, and state reset logic can share a single source of truth.

Field categories
----------------
PERSISTENT
    Conversation data that survives across turns and should be saved to
    durable storage. Messages, pinned facts, task brief, rolling summary,
    accumulated artifacts/citations, and per-thread selections (model,
    thinking mode) all belong here.

TRANSIENT
    Per-turn working state that is regenerated each turn and must be
    cleared before the next turn begins. Examples: assembled_context,
    retrieved_memories, plan, reflection, current_step_id, prompt blocks,
    pending tool actions, and the active merge review payloads.

OBSERVABLE
    Governance and observability records that are conceptually append-only
    event logs. The canonical store is ``governance_records``; mirrored
    convenience keys (tool_route_plan, execution_contract, answer_verification,
    etc.) are classified here as well so they can be drained into a
    GovernanceLog rather than round-tripped through persistent state.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Persistent fields: survive across turns; belong in durable storage.
# ---------------------------------------------------------------------------
PERSISTENT_FIELDS: frozenset[str] = frozenset(
    {
        # Conversation backbone
        "messages",
        "task_brief",
        "rolling_summary",
        # User-curated facts and goals
        "pinned_facts",
        "pinned_items",
        "user_constraints",
        "active_goal",
        "active_plan",
        # Accumulated artifacts and evidence
        "artifacts",
        "citations",
        # Branch/merge durable state
        "branch_local_findings",
        "imported_findings",
        "merge_queue",
        # Counters and per-thread selections
        "llm_calls",
        "selected_model",
        "selected_thinking_mode",
        # Stable execution policy set at thread/turn start
        "context_budget",
        "prompt_mode",
    }
)

# ---------------------------------------------------------------------------
# Transient fields: per-turn working state; cleared between turns.
# ---------------------------------------------------------------------------
TRANSIENT_FIELDS: frozenset[str] = frozenset(
    {
        # Clipped/assembled prompt surface for the current turn
        "recent_messages",
        "assembled_context",
        "available_skills_block",
        "active_skills_block",
        # Memory retrieval snapshots (regenerated each turn)
        "retrieved_memories",
        "memory_prompt_block",
        "memory_retrieval_plan",
        # Active turn skill selection
        "active_skill_ids",
        # Plan-Act-Reflect working state
        "plan",
        "current_step_id",
        "reflection",
        # Branch execution scratch (reset between branch invocations)
        "branch_meta",
        "branch_actions",
        "merge_proposal",
        "merge_decision",
        # Pending tool action for the next loop iteration
        "pending_tool_action",
        # Transient write queue drained by write_memories node
        "memory_write_requests",
    }
)

# ---------------------------------------------------------------------------
# Observable fields: governance/observability records (append-only logs).
# ---------------------------------------------------------------------------
OBSERVABLE_FIELDS: frozenset[str] = frozenset(
    {
        # Canonical append-only governance record log
        "governance_records",
        # Mirrored governance keys (latest-payload mirrors into top-level state)
        "role_route_plan",
        "memory_curator_decision",
        "tool_intent_plan",
        "tool_route_plan",
        "evidence_bundle",
        "evidence_ledger",
        "execution_contract",
        "answer_verification",
        "tool_outcomes",
        "task_outcome",
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
        # Audit/observability containers
        "branch_action_audit",
        "plan_meta",
    }
)

# Sentinel defaults used when resetting transient fields. Mirrors
# ``initial_agent_state()`` from .state without creating a circular import.
_TRANSIENT_DEFAULTS: dict[str, Any] = {
    "recent_messages": [],
    "assembled_context": "",
    "available_skills_block": "",
    "active_skills_block": "",
    "retrieved_memories": [],
    "memory_prompt_block": "",
    "memory_retrieval_plan": {},
    "active_skill_ids": [],
    "plan": None,
    "current_step_id": "",
    "reflection": None,
    "branch_meta": None,
    "branch_actions": [],
    "merge_proposal": None,
    "merge_decision": None,
    "pending_tool_action": None,
    "memory_write_requests": [],
}


def categorize_field(field_name: str) -> str:
    """Return the lifecycle category for a single AgentState field.

    Parameters
    ----------
    field_name:
        Key name as it appears in ``AgentState``.

    Returns
    -------
    str
        One of ``"persistent"``, ``"transient"``, ``"observable"``, or
        ``"unknown"`` for unrecognized fields.
    """
    if field_name in PERSISTENT_FIELDS:
        return "persistent"
    if field_name in TRANSIENT_FIELDS:
        return "transient"
    if field_name in OBSERVABLE_FIELDS:
        return "observable"
    return "unknown"


def extract_persistent_state(state: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy containing only PERSISTENT fields."""
    return {key: value for key, value in state.items() if key in PERSISTENT_FIELDS}


def extract_transient_state(state: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy containing only TRANSIENT fields."""
    return {key: value for key, value in state.items() if key in TRANSIENT_FIELDS}


def extract_observable_state(state: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy containing only OBSERVABLE fields."""
    return {key: value for key, value in state.items() if key in OBSERVABLE_FIELDS}


def clear_transient_state(state: dict[str, Any]) -> dict[str, Any]:
    """Return a new dict with transient fields reset to their initial defaults.

    Persistent and observable fields are preserved as-is. The returned dict
    is a shallow copy; callers may mutate it safely without affecting the
    input mapping.
    """
    cleared: dict[str, Any] = {
        key: value
        for key, value in state.items()
        if key not in TRANSIENT_FIELDS
    }
    for key, default in _TRANSIENT_DEFAULTS.items():
        cleared[key] = default
    return cleared


def merge_persistent_into_state(
    persistent: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    """Merge a persistent-state snapshot into a working state dict.

    Persistent keys from ``persistent`` overwrite those in ``state``.
    Non-persistent keys in ``persistent`` are ignored. Existing non-persistent
    keys in ``state`` are preserved. The return value is a new dict (the
    inputs are not mutated).

    Notes
    -----
    For list-valued fields annotated with ``operator.add`` (messages,
    pinned_facts, user_constraints, etc.) this performs *replace* semantics:
    the persistent snapshot is treated as the source of truth. Callers that
    need incremental append semantics should merge at the LangGraph channel
    level instead.
    """
    merged: dict[str, Any] = dict(state)
    for key, value in persistent.items():
        if key in PERSISTENT_FIELDS:
            merged[key] = value
    return merged


__all__ = [
    "PERSISTENT_FIELDS",
    "TRANSIENT_FIELDS",
    "OBSERVABLE_FIELDS",
    "categorize_field",
    "clear_transient_state",
    "extract_observable_state",
    "extract_persistent_state",
    "extract_transient_state",
    "merge_persistent_into_state",
]
