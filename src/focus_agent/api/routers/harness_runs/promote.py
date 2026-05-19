from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from focus_agent.engine.runtime import AppRuntime
from focus_agent.security.tokens import Principal
from focus_agent.services.chat import ChatService

from ...deps import get_app_runtime, get_chat_service, get_current_principal
from .replay import (
    HarnessRunCancelRequest,
    HarnessRunResponse,
    _harness_run_response,
    _load_authorized_run_payload,
)

router = APIRouter(prefix="/v2", tags=["harness-runs"])


@router.post("/runs/{run_id}/cancel", response_model=HarnessRunResponse)
async def cancel_harness_run(
    run_id: str,
    payload: HarnessRunCancelRequest,
    runtime: AppRuntime = Depends(get_app_runtime),
    chat: ChatService = Depends(get_chat_service),
    principal: Principal = Depends(get_current_principal),
) -> HarnessRunResponse:
    await _load_authorized_run_payload(
        runtime=runtime,
        chat=chat,
        principal=principal,
        run_id=run_id,
    )
    action = "rollback" if payload.action == "rollback" else "interrupt"
    cancelled = await runtime.run_manager.cancel(run_id, action=action)
    if not cancelled:
        raise HTTPException(status_code=404, detail=f"Active run not found: {run_id}")
    return _harness_run_response(
        runtime=runtime,
        run_id=run_id,
        fallback_record={"run_id": run_id},
    )
