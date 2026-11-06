from __future__ import annotations

from fastapi import APIRouter, Depends

from focus_agent.engine.runtime import AppRuntime
from focus_agent.security.tokens import Principal
from focus_agent.services.chat import ChatService

from ...deps import get_app_runtime, get_chat_service, get_current_principal
from ...route_helpers import run_sync_route_call
from .replay_helpers import _harness_run_response, _load_authorized_run_payload
from .replay_models import HarnessRunCancelRequest, HarnessRunResponse
from .replay_payloads import _preflight_thread_access

router = APIRouter(prefix="/v2", tags=["harness-runs"])


@router.post("/runs/{run_id}/cancel", response_model=HarnessRunResponse)
async def cancel_harness_run(
    run_id: str,
    payload: HarnessRunCancelRequest,
    runtime: AppRuntime = Depends(get_app_runtime),
    chat: ChatService = Depends(get_chat_service),
    principal: Principal = Depends(get_current_principal),
) -> HarnessRunResponse:
    run_payload = await _load_authorized_run_payload(
        runtime=runtime,
        chat=chat,
        principal=principal,
        run_id=run_id,
    )
    action = "rollback" if payload.action == "rollback" else "interrupt"
    # Idempotent: a run that already stopped (e.g. cancelled by stream disconnect)
    # returns its current record; unknown runs already 404 above.
    await runtime.run_manager.cancel(run_id, action=action)
    return _harness_run_response(runtime=runtime, run_id=run_id, fallback_record=run_payload)


@router.post("/threads/{thread_id:path}/runs/cancel")
async def cancel_thread_harness_runs(
    thread_id: str,
    payload: HarnessRunCancelRequest,
    runtime: AppRuntime = Depends(get_app_runtime),
    chat: ChatService = Depends(get_chat_service),
    principal: Principal = Depends(get_current_principal),
) -> dict[str, object]:
    await run_sync_route_call(
        _preflight_thread_access,
        chat,
        thread_id=thread_id,
        user_id=principal.user_id,
        explicit_skill_hints=(),
        require_writable=False,
    )
    action = "rollback" if payload.action == "rollback" else "interrupt"
    cancelled_run_ids = await runtime.run_manager.cancel_thread(
        thread_id,
        user_id=principal.user_id,
        action=action,
    )
    return {
        "thread_id": thread_id,
        "cancelled_run_ids": cancelled_run_ids,
        "cancelled_count": len(cancelled_run_ids),
    }
