from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from uuid import uuid4

from ..config import Settings
from .delegation_models import (
    AgentFailureRecord,
    AgentReviewItem,
    AgentSelfRepairPreview,
)
from .roles import AgentRole, normalize_agent_role


def build_failure_records(
    *,
    delegation_plan: dict[str, Any] | None = None,
    tool_route_plan: dict[str, Any] | None = None,
    model_route_decision: dict[str, Any] | None = None,
    trajectory_id: str | None = None,
) -> list[AgentFailureRecord]:
    records: list[AgentFailureRecord] = []
    route_plan = tool_route_plan if isinstance(tool_route_plan, dict) else {}
    denied_tools = route_plan.get("denied_tools") or []
    if denied_tools:
        records.append(
            AgentFailureRecord(
                failure_id=f"failure-{uuid4().hex[:12]}",
                failure_type="tool_denied",
                failed_role=normalize_agent_role(
                    str(route_plan.get("role") or AgentRole.EXECUTOR.value)
                ),
                failed_task_id=_first_task_id(delegation_plan),
                tool_route_plan=route_plan,
                model_id=(model_route_decision or {}).get("effective_model")
                if isinstance(model_route_decision, dict)
                else None,
                trajectory_id=trajectory_id,
                message=f"Tool Router denied {len(denied_tools)} tool(s).",
            )
        )
    if isinstance(delegation_plan, dict):
        for raw in delegation_plan.get("runs") or []:
            if isinstance(raw, dict) and raw.get("status") == "failed":
                records.append(
                    AgentFailureRecord(
                        failure_id=f"failure-{uuid4().hex[:12]}",
                        failure_type="critic_rejected",
                        failed_role=normalize_agent_role(
                            str(raw.get("role") or AgentRole.CRITIC.value)
                        ),
                        failed_task_id=raw.get("task_id"),
                        tool_route_plan=route_plan,
                        model_id=raw.get("model_id"),
                        trajectory_id=trajectory_id,
                        message=str(raw.get("error") or "Delegated run failed."),
                    )
                )
    return records


def build_self_repair_preview(
    *,
    failures: Iterable[dict[str, Any] | AgentFailureRecord],
    case_id_prefix: str = "agent_delegation",
) -> AgentSelfRepairPreview:
    normalized = [
        item if isinstance(item, AgentFailureRecord) else AgentFailureRecord.model_validate(item)
        for item in failures
    ]
    candidates = [
        {
            "id": f"{case_id_prefix}_{failure.failure_type}_{index + 1}",
            "tags": ["agent_delegation", "self_repair", failure.failure_type],
            "input": {
                "user_message": failure.message or "Replay failed delegated agent behavior.",
                "initial_state": {"agent_failure_records": [failure.model_dump(mode="json")]},
            },
            "expected": {
                "answer_contains_any": [
                    failure.failure_type,
                    failure.failed_role.value,
                    "retry",
                    "denied",
                ],
                "must_not_call_tools": ["web_search", "web_fetch"]
                if failure.failure_type == "tool_denied"
                else [],
            },
            "judge": {"rule": True, "llm": {"enabled": False}},
        }
        for index, failure in enumerate(normalized)
    ]
    return AgentSelfRepairPreview(enabled=True, candidates=candidates, failures=normalized)


def build_review_queue(
    *,
    settings: Settings,
    memory_curator_decision: dict[str, Any] | None = None,
    tool_route_plan: dict[str, Any] | None = None,
    model_route_decision: dict[str, Any] | None = None,
    agent_failure_records: Iterable[dict[str, Any]] = (),
) -> list[AgentReviewItem]:
    if not bool(getattr(settings, "agent_review_queue_enabled", False)):
        return []
    items: list[AgentReviewItem] = []
    memory_decision = memory_curator_decision if isinstance(memory_curator_decision, dict) else {}
    if memory_decision.get("conflicts"):
        items.append(
            AgentReviewItem(
                item_id=f"review-{uuid4().hex[:12]}",
                item_type="memory_promotion_conflict",
                role=AgentRole.MEMORY_CURATOR,
                summary="Memory Curator found semantic conflicts before promotion.",
                payload=memory_decision,
            )
        )
    route_plan = tool_route_plan if isinstance(tool_route_plan, dict) else {}
    denied_tools = set(str(item) for item in route_plan.get("denied_tools") or [])
    if denied_tools.intersection({"write_text_artifact", "artifact_update"}):
        items.append(
            AgentReviewItem(
                item_id=f"review-{uuid4().hex[:12]}",
                item_type="workspace_write_with_high_risk_tool",
                role=normalize_agent_role(str(route_plan.get("role") or AgentRole.EXECUTOR.value)),
                summary="Workspace write was denied by Tool Router and requires review.",
                payload=route_plan,
            )
        )
    model_decision = model_route_decision if isinstance(model_route_decision, dict) else {}
    if (
        model_decision.get("enabled")
        and model_decision.get("mode") == "enforce"
        and model_decision.get("selected_model") != model_decision.get("effective_model")
    ):
        items.append(
            AgentReviewItem(
                item_id=f"review-{uuid4().hex[:12]}",
                item_type="model_router_enforce_override",
                role=normalize_agent_role(
                    str(model_decision.get("role") or AgentRole.EXECUTOR.value)
                ),
                summary="Model Router changed the effective model under enforce mode.",
                payload=model_decision,
            )
        )
    for raw in agent_failure_records:
        if raw.get("failure_type") == "critic_rejected":
            items.append(
                AgentReviewItem(
                    item_id=f"review-{uuid4().hex[:12]}",
                    item_type="critic_rejected_continue_request",
                    role=normalize_agent_role(
                        str(raw.get("failed_role") or AgentRole.CRITIC.value)
                    ),
                    task_id=raw.get("failed_task_id"),
                    summary=str(raw.get("message") or "Critic rejected a delegated run."),
                    payload=dict(raw),
                )
            )
    return items


def apply_review_decision(item: dict[str, Any], *, approved: bool) -> AgentReviewItem:
    review = AgentReviewItem.model_validate(item)
    return review.model_copy(update={"status": "approved" if approved else "rejected"})


def _first_task_id(delegation_plan: dict[str, Any] | None) -> str | None:
    if not isinstance(delegation_plan, dict):
        return None
    tasks = delegation_plan.get("tasks") or []
    if tasks and isinstance(tasks[0], dict):
        return tasks[0].get("task_id")
    return None


__all__ = [
    "apply_review_decision",
    "build_failure_records",
    "build_review_queue",
    "build_self_repair_preview",
]
