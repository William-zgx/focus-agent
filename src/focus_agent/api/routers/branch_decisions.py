from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from focus_agent.engine.runtime import AppRuntime
from focus_agent.security.tokens import Principal
from focus_agent.services.chat import ConcurrentTurnError

from ..contracts import (
    BranchDecisionConfigResponse,
    BranchDecisionDismissRequest,
    BranchDecisionEventResponse,
    BranchDecisionListResponse,
)
from ..deps import get_app_runtime, get_current_principal
from ..route_helpers import run_sync_route_call
from ..route_utils.branch_handoff_decisions import ensure_branch_handoff_decision_from_journal

router = APIRouter()


@router.get("/v1/branch-decisions/config", response_model=BranchDecisionConfigResponse)
def get_branch_decision_config(
    runtime: AppRuntime = Depends(get_app_runtime),
    principal: Principal = Depends(get_current_principal),
) -> BranchDecisionConfigResponse:
    del principal
    service = _branch_decision_service(runtime)
    return BranchDecisionConfigResponse.model_validate(service.config().model_dump(mode="json"))


@router.get(
    "/v1/threads/{thread_id:path}/branch-decisions", response_model=BranchDecisionListResponse
)
async def list_thread_branch_decisions(
    thread_id: str,
    request: Request,
    status: str | None = None,
    action: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    runtime: AppRuntime = Depends(get_app_runtime),
    principal: Principal = Depends(get_current_principal),
) -> BranchDecisionListResponse:
    service = _branch_decision_service(runtime)
    try:
        await ensure_branch_handoff_decision_from_journal(
            runtime=runtime,
            thread_id=thread_id,
            user_id=principal.user_id,
            request_id=getattr(getattr(request, "state", None), "request_id", None),
        )
        events = await run_sync_route_call(
            service.list_decisions,
            thread_id=thread_id,
            user_id=principal.user_id,
            status=status,
            action=action,
            limit=limit,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return BranchDecisionListResponse(
        items=[
            BranchDecisionEventResponse.model_validate(item.model_dump(mode="json"))
            for item in events
        ],
        count=len(events),
    )


@router.post(
    "/v1/threads/{thread_id:path}/branch-decisions/{decision_id}/promote",
    response_model=BranchDecisionEventResponse,
)
def promote_thread_branch_decision(
    thread_id: str,
    decision_id: str,
    request: Request,
    runtime: AppRuntime = Depends(get_app_runtime),
    principal: Principal = Depends(get_current_principal),
) -> BranchDecisionEventResponse:
    service = _branch_decision_service(runtime)
    try:
        event = service.promote_decision(
            thread_id=thread_id,
            decision_id=decision_id,
            user_id=principal.user_id,
            request_id=getattr(request.state, "request_id", None),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConcurrentTurnError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return BranchDecisionEventResponse.model_validate(event.model_dump(mode="json"))


@router.post(
    "/v1/threads/{thread_id:path}/branch-decisions/{decision_id}/dismiss",
    response_model=BranchDecisionEventResponse,
)
def dismiss_thread_branch_decision(
    thread_id: str,
    decision_id: str,
    payload: BranchDecisionDismissRequest | None = None,
    runtime: AppRuntime = Depends(get_app_runtime),
    principal: Principal = Depends(get_current_principal),
) -> BranchDecisionEventResponse:
    service = _branch_decision_service(runtime)
    try:
        event = service.dismiss_decision(
            thread_id=thread_id,
            decision_id=decision_id,
            user_id=principal.user_id,
            reason=(payload.reason if payload is not None else None),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return BranchDecisionEventResponse.model_validate(event.model_dump(mode="json"))


def _branch_decision_service(runtime: AppRuntime):
    service = getattr(runtime, "branch_decision_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Branch decision service is not configured.")
    return service


__all__ = ["router"]
