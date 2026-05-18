from __future__ import annotations

from typing import Any

from focus_agent.config import Settings
from focus_agent.core.branching import BranchRecord, BranchRole, BranchStatus
from focus_agent.core.request_context import RequestContext
from focus_agent.engine.runtime import AppRuntime
from focus_agent.memory import MemoryCurator

from ..contracts import (
    AgentMemoryCuratorDecisionListResponse,
    AgentMemoryCuratorEvaluateRequest,
    AgentMemoryCuratorEvaluateResponse,
    AgentMemoryCuratorPolicyResponse,
)
from .agent_governance_trajectory_responses import _list_response_fields


def _agent_memory_curator_policy_response(
    settings: Settings | Any,
) -> AgentMemoryCuratorPolicyResponse:
    return AgentMemoryCuratorPolicyResponse(
        enabled=bool(getattr(settings, "agent_memory_curator_enabled", False)),
        auto_promote_on_merge=bool(getattr(settings, "agent_memory_auto_promote_on_merge", True)),
    )


def _agent_memory_curator_evaluate_response(
    *,
    payload: AgentMemoryCuratorEvaluateRequest,
    runtime: AppRuntime | Any,
    principal_user_id: str,
) -> AgentMemoryCuratorEvaluateResponse:
    branch_record = BranchRecord(
        branch_id=payload.branch_id,
        root_thread_id=payload.root_thread_id,
        parent_thread_id=payload.parent_thread_id or payload.root_thread_id,
        child_thread_id=payload.child_thread_id or payload.branch_id,
        return_thread_id=payload.parent_thread_id or payload.root_thread_id,
        owner_user_id=payload.user_id or principal_user_id,
        branch_name=payload.branch_name,
        branch_role=BranchRole(payload.branch_role),
        branch_depth=1,
        branch_status=BranchStatus(payload.branch_status),
    )
    context = RequestContext(
        user_id=payload.user_id or principal_user_id,
        root_thread_id=payload.root_thread_id,
        parent_thread_id=payload.parent_thread_id or payload.root_thread_id,
        branch_id=payload.branch_id,
        branch_role=payload.branch_role,
    )
    curator = MemoryCurator(store=getattr(runtime, "store", None))
    decision = curator.evaluate_branch_promotion(
        branch_record=branch_record,
        findings=payload.findings,
        context=context,
        auto_promote=(
            bool(getattr(runtime.settings, "agent_memory_auto_promote_on_merge", True))
            if payload.auto_promote is None
            else bool(payload.auto_promote)
        ),
    )
    return AgentMemoryCuratorEvaluateResponse(decision=decision.model_dump(mode="json"))


def _agent_memory_curator_decisions_response(
    *,
    runtime: AppRuntime | Any,
    limit: int,
) -> AgentMemoryCuratorDecisionListResponse:
    return AgentMemoryCuratorDecisionListResponse(
        **_list_response_fields(
            runtime=runtime, key="memory_curator_decision", limit=limit, decisions=True
        )
    )


__all__ = [
    "_agent_memory_curator_decisions_response",
    "_agent_memory_curator_evaluate_response",
    "_agent_memory_curator_policy_response",
]
