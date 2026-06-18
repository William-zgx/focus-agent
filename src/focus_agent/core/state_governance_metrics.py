from __future__ import annotations

from collections.abc import Mapping
from typing import Any

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
    "tool_intent_direct_answer",
    "tool_intent_workspace_lookup",
    "tool_intent_live_web_research",
    "tool_intent_execution",
    "tool_intent_first_tool",
    "tool_intent_carryover",
    "temporal_anchor_forced",
    "memory_quality_skipped",
    "external_answer_missing_citation",
    "mandatory_tool_missed",
    "contract_blocked",
    "answer_verification_failed",
    "contradiction_blocked",
    "generic_delegation_skipped",
    "memory_write_blocked",
    "agent_task_ledger_tasks",
    "delegated_artifacts",
    "critic_gate_rejected",
    "tool_failures",
    "tool_blocked",
    "tool_recovered",
    "tool_fallback_uses",
    "degraded_answers",
    "blocked_task_outcomes",
)


def memory_curator_metrics(payload: Any) -> Mapping[str, int]:
    if not isinstance(payload, Mapping):
        return {}
    return {
        "memory_promotions": len(payload.get("promoted_memory_ids") or []),
        "memory_conflicts": len(payload.get("conflicts") or []),
    }


def tool_route_metrics(payload: Any) -> Mapping[str, int]:
    if not isinstance(payload, Mapping):
        return {}
    return {
        "tool_router_denied": len(payload.get("denied_tools") or []),
        "tool_router_enforced": 1 if payload.get("enforce") else 0,
    }


def tool_intent_metrics(payload: Any) -> Mapping[str, int]:
    if not isinstance(payload, Mapping):
        return {}
    policy = str(payload.get("policy") or "").strip()
    preferred_first_tool = str(payload.get("preferred_first_tool") or "").strip()
    reason_codes = {str(item) for item in payload.get("reason_codes") or [] if str(item)}
    return {
        "tool_intent_direct_answer": 1 if policy == "direct_answer" else 0,
        "tool_intent_workspace_lookup": 1 if policy == "workspace_lookup" else 0,
        "tool_intent_live_web_research": 1 if policy == "live_web_research" else 0,
        "tool_intent_execution": 1 if policy == "execution" else 0,
        "tool_intent_first_tool": 1 if preferred_first_tool else 0,
        "tool_intent_carryover": 1 if "pending_tool_action_carryover" in reason_codes else 0,
        "temporal_anchor_forced": 1 if payload.get("temporal_anchor_forced") else 0,
        "external_answer_missing_citation": 1
        if payload.get("external_answer_missing_citation")
        else 0,
    }


def memory_write_metrics(payload: Any) -> Mapping[str, int]:
    if not isinstance(payload, Mapping):
        return {}
    skipped = payload.get("skipped") or []
    if not isinstance(skipped, list):
        return {}
    quality_reasons = {
        "unstable_self_correction",
        "claimed_tool_use_without_result",
        "external_claim_without_evidence",
        "answer_verification_failed",
    }
    return {
        "memory_quality_skipped": len(
            [
                item
                for item in skipped
                if isinstance(item, Mapping) and str(item.get("reason") or "") in quality_reasons
            ]
        ),
        "memory_write_blocked": len(
            [
                item
                for item in skipped
                if isinstance(item, Mapping)
                and str(item.get("reason") or "") == "answer_verification_failed"
            ]
        ),
    }


def agent_delegation_metrics(payload: Any) -> Mapping[str, int]:
    if not isinstance(payload, Mapping):
        return {}
    return {
        "agent_delegation_runs": len(payload.get("runs") or []),
        "generic_delegation_skipped": 1
        if str(payload.get("skipped_reason") or "") == "no_valid_route_decisions"
        else 0,
    }


def execution_contract_metrics(payload: Any) -> Mapping[str, int]:
    if not isinstance(payload, Mapping):
        return {}
    status = str(payload.get("status") or "")
    missing = payload.get("missing") or []
    return {
        "mandatory_tool_missed": len(missing) if status == "missing_required_tools" else 0,
        "contract_blocked": 1 if status == "blocked" else 0,
    }


def answer_verification_metrics(payload: Any) -> Mapping[str, int]:
    if not isinstance(payload, Mapping):
        return {}
    status = str(payload.get("status") or "")
    return {
        "answer_verification_failed": 1
        if status in {"unsupported", "contradicted", "blocked"}
        else 0,
        "contradiction_blocked": 1 if status == "contradicted" else 0,
    }


def tool_outcome_metrics(payload: Any) -> Mapping[str, int]:
    if not isinstance(payload, list):
        return {}
    outcomes = [item for item in payload if isinstance(item, Mapping)]
    return {
        "tool_failures": len([item for item in outcomes if item.get("status") == "failed"]),
        "tool_blocked": len([item for item in outcomes if item.get("status") == "blocked"]),
        "tool_recovered": len([item for item in outcomes if item.get("status") == "recovered"]),
        "tool_fallback_uses": len([item for item in outcomes if item.get("fallback_used")]),
    }


def task_outcome_metrics(payload: Any) -> Mapping[str, int]:
    if not isinstance(payload, Mapping):
        return {}
    status = str(payload.get("status") or "")
    return {
        "degraded_answers": 1 if status == "degraded_answer" else 0,
        "blocked_task_outcomes": 1 if status == "blocked" else 0,
    }


def model_route_metrics(payload: Any) -> Mapping[str, int]:
    if not isinstance(payload, Mapping):
        return {}
    return {"model_router_fallback": 1 if payload.get("fallback_used") else 0}


def agent_failure_metrics(payload: Any) -> Mapping[str, int]:
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


def agent_review_metrics(payload: Any) -> Mapping[str, int]:
    if not isinstance(payload, list):
        return {}
    return {
        "agent_review_pending": len(
            [
                item
                for item in payload
                if isinstance(item, Mapping) and item.get("status") == "pending"
            ]
        )
    }


def context_artifact_ref_metrics(payload: Any) -> Mapping[str, int]:
    if not isinstance(payload, list):
        return {}
    return {"context_artifact_refs": len(payload)}


def context_budget_metrics(payload: Any) -> Mapping[str, int]:
    if not isinstance(payload, Mapping):
        return {}
    return {"context_over_budget": 1 if int(payload.get("over_budget_chars") or 0) > 0 else 0}


def agent_task_ledger_metrics(payload: Any) -> Mapping[str, int]:
    if not isinstance(payload, Mapping):
        return {}
    return {"agent_task_ledger_tasks": len(payload.get("tasks") or [])}


def delegated_artifact_metrics(payload: Any) -> Mapping[str, int]:
    if not isinstance(payload, list):
        return {}
    return {"delegated_artifacts": len(payload)}


def critic_gate_metrics(payload: Any) -> Mapping[str, int]:
    if not isinstance(payload, Mapping):
        return {}
    return {"critic_gate_rejected": len(payload.get("rejected_artifact_ids") or [])}


__all__ = [
    "GOVERNANCE_METRIC_KEYS",
    "agent_delegation_metrics",
    "answer_verification_metrics",
    "agent_failure_metrics",
    "agent_review_metrics",
    "agent_task_ledger_metrics",
    "context_artifact_ref_metrics",
    "context_budget_metrics",
    "critic_gate_metrics",
    "delegated_artifact_metrics",
    "execution_contract_metrics",
    "memory_curator_metrics",
    "memory_write_metrics",
    "model_route_metrics",
    "task_outcome_metrics",
    "tool_outcome_metrics",
    "tool_intent_metrics",
    "tool_route_metrics",
]
