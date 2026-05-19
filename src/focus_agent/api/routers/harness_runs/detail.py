from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from focus_agent.engine.runtime import AppRuntime
from focus_agent.security.tokens import Principal
from focus_agent.services.chat import ChatService

from ...deps import get_app_runtime, get_chat_service, get_current_principal
from .replay import (
    HarnessRunResponse,
    _journal_method,
    _json_safe,
    _load_authorized_run_payload,
    _run_event_streaming_response,
)

router = APIRouter(prefix="/v2", tags=["harness-runs"])


@router.post("/runs/{run_id}/stream")
async def stream_existing_harness_run(
    run_id: str,
    request: Request,
    runtime: AppRuntime = Depends(get_app_runtime),
    chat: ChatService = Depends(get_chat_service),
    principal: Principal = Depends(get_current_principal),
) -> StreamingResponse:
    run_payload = await _load_authorized_run_payload(
        runtime=runtime,
        chat=chat,
        principal=principal,
        run_id=run_id,
    )
    return _run_event_streaming_response(
        runtime=runtime,
        run_id=run_id,
        thread_id=str(run_payload["thread_id"]),
        request=request,
        cancel_on_disconnect=False,
    )


@router.get("/runs/{run_id}/snapshot")
async def get_harness_run_snapshot(
    run_id: str,
    runtime: AppRuntime = Depends(get_app_runtime),
    chat: ChatService = Depends(get_chat_service),
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    await _load_authorized_run_payload(
        runtime=runtime,
        chat=chat,
        principal=principal,
        run_id=run_id,
    )
    snapshot = await _journal_method(runtime, "snapshot")(run_id)
    return _json_safe(snapshot)


@router.get("/runs/{run_id}/trajectory")
async def get_harness_run_trajectory(
    run_id: str,
    runtime: AppRuntime = Depends(get_app_runtime),
    chat: ChatService = Depends(get_chat_service),
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    await _load_authorized_run_payload(
        runtime=runtime,
        chat=chat,
        principal=principal,
        run_id=run_id,
    )
    trajectory = await _journal_method(runtime, "trajectory_summary")(run_id)
    return _json_safe(trajectory)


@router.get("/runs/{run_id}", response_model=HarnessRunResponse)
async def get_harness_run(
    run_id: str,
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
    return HarnessRunResponse(run=run_payload, thread_state=None)
