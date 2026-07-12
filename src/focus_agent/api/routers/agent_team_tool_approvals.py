from __future__ import annotations

from types import ModuleType

from fastapi import APIRouter, Depends

from focus_agent.engine.runtime import AppRuntime
from focus_agent.security.tokens import Principal

from ..contract_models.agent_team import (
    AgentTeamToolApprovalActionRequest,
    AgentTeamToolApprovalContract,
    AgentTeamToolApprovalDecisionResponse,
    AgentTeamToolApprovalListResponse,
    DecideAgentTeamToolApprovalRequest,
)
from ..deps import get_app_runtime, get_current_principal

router = APIRouter()


def _root_agent_team_module() -> ModuleType:
    from . import agent_team

    return agent_team


@router.get(
    "/v1/agent-team/sessions/{session_id}/tool-approvals",
    response_model=AgentTeamToolApprovalListResponse,
)
def list_agent_team_tool_approvals(
    session_id: str,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamToolApprovalListResponse:
    agent_team = _root_agent_team_module()
    service = agent_team._agent_team_service_or_503(runtime)
    try:
        session = service.get_session(session_id, user_id=principal.user_id)
        approvals = agent_team._pending_tool_approvals_for_session(service, session)
    except Exception as exc:  # noqa: BLE001
        raise agent_team._agent_team_error(exc) from exc
    return AgentTeamToolApprovalListResponse(
        approvals=approvals,
        items=approvals,
        count=len(approvals),
    )


@router.post(
    "/v1/agent-team/sessions/{session_id}/tool-approvals/{request_id}/decision",
    response_model=AgentTeamToolApprovalDecisionResponse,
)
def decide_agent_team_tool_approval(
    session_id: str,
    request_id: str,
    payload: DecideAgentTeamToolApprovalRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamToolApprovalDecisionResponse:
    agent_team = _root_agent_team_module()
    service = agent_team._agent_team_service_or_503(runtime)
    try:
        session = service.get_session(session_id, user_id=principal.user_id)
        approval_queue = agent_team._agent_team_approval_queue(service)
        request = agent_team._get_tool_approval_request(approval_queue, request_id)
        if request is None or str(request.session_id) not in {
            session.session_id,
            session.root_thread_id,
        }:
            raise KeyError(request_id)
        approval_queue.decide(
            request_id=request_id,
            approved=payload.approved,
            decided_by=principal.user_id,
        )
        decided = agent_team._get_tool_approval_request(approval_queue, request_id) or request
    except Exception as exc:  # noqa: BLE001
        raise agent_team._agent_team_error(exc) from exc
    return AgentTeamToolApprovalDecisionResponse(
        approval=AgentTeamToolApprovalContract.model_validate(
            agent_team._tool_approval_payload(decided)
        )
    )


@router.post(
    "/v1/agent-team/sessions/{session_id}/tool-approvals/{request_id}/approve",
    response_model=AgentTeamToolApprovalDecisionResponse,
)
def approve_agent_team_tool_approval(
    session_id: str,
    request_id: str,
    payload: AgentTeamToolApprovalActionRequest | None = None,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamToolApprovalDecisionResponse:
    return _root_agent_team_module().decide_agent_team_tool_approval(
        session_id=session_id,
        request_id=request_id,
        payload=DecideAgentTeamToolApprovalRequest(
            approved=True,
            reason=payload.reason if payload else None,
        ),
        principal=principal,
        runtime=runtime,
    )


@router.post(
    "/v1/agent-team/sessions/{session_id}/tool-approvals/{request_id}/reject",
    response_model=AgentTeamToolApprovalDecisionResponse,
)
def reject_agent_team_tool_approval(
    session_id: str,
    request_id: str,
    payload: AgentTeamToolApprovalActionRequest | None = None,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamToolApprovalDecisionResponse:
    return _root_agent_team_module().decide_agent_team_tool_approval(
        session_id=session_id,
        request_id=request_id,
        payload=DecideAgentTeamToolApprovalRequest(
            approved=False,
            reason=payload.reason if payload else None,
        ),
        principal=principal,
        runtime=runtime,
    )


def _agent_team_approval_queue(service: object):
    coordination_backend = getattr(service, "coordination_backend", None)
    approval_queue = getattr(coordination_backend, "approval_queue", None)
    if approval_queue is None:
        raise RuntimeError("Agent Team tool approval queue is unavailable.")
    return approval_queue


def _pending_tool_approvals_for_session(
    service: object,
    session: object,
) -> list[AgentTeamToolApprovalContract]:
    agent_team = _root_agent_team_module()
    approval_queue = agent_team._agent_team_approval_queue(service)
    if not hasattr(approval_queue, "list_pending"):
        return []
    session_ids = {
        str(getattr(session, "session_id", "")),
        str(getattr(session, "root_thread_id", "")),
    }
    approvals = []
    for request in approval_queue.list_pending():
        if str(getattr(request, "session_id", "")) in session_ids:
            approvals.append(
                AgentTeamToolApprovalContract.model_validate(
                    agent_team._tool_approval_payload(request)
                )
            )
    return approvals


def _get_tool_approval_request(approval_queue: object, request_id: str):
    get = getattr(approval_queue, "get", None)
    if callable(get):
        return get(request_id)
    if not hasattr(approval_queue, "list_pending"):
        return None
    for request in approval_queue.list_pending():
        if str(getattr(request, "request_id", "")) == request_id:
            return request
    return None


def _tool_approval_payload(request: object) -> dict[str, object]:
    status = getattr(request, "status", "pending")
    status_value = getattr(status, "value", status)
    return {
        "request_id": str(getattr(request, "request_id", "")),
        "session_id": str(getattr(request, "session_id", "")),
        "agent_id": str(getattr(request, "agent_id", "")),
        "tool_name": str(getattr(request, "tool_name", "")),
        "tool_args": dict(getattr(request, "tool_args", {}) or {}),
        "risk_level": str(getattr(request, "risk_level", "low") or "low"),
        "status": str(status_value or "pending"),
        "submitted_at": float(getattr(request, "submitted_at", 0.0) or 0.0),
        "timeout_at": float(getattr(request, "timeout_at", 0.0) or 0.0),
        "decided_by": getattr(request, "decided_by", None),
    }


__all__ = [
    "_agent_team_approval_queue",
    "_get_tool_approval_request",
    "_pending_tool_approvals_for_session",
    "_tool_approval_payload",
    "approve_agent_team_tool_approval",
    "decide_agent_team_tool_approval",
    "list_agent_team_tool_approvals",
    "reject_agent_team_tool_approval",
    "router",
]
