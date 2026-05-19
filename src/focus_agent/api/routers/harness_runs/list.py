from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from focus_agent.engine.runtime import AppRuntime
from focus_agent.security.tokens import Principal
from focus_agent.services.chat import ChatService

from ...deps import get_app_runtime, get_chat_service, get_current_principal
from .replay import _journal_method, _json_safe, _load_authorized_run_payload

router = APIRouter(prefix="/v2", tags=["harness-runs"])


@router.get("/runs/{run_id}/events")
async def list_harness_run_events(
    run_id: str,
    runtime: AppRuntime = Depends(get_app_runtime),
    chat: ChatService = Depends(get_chat_service),
    principal: Principal = Depends(get_current_principal),
    event: str | None = None,
    limit: int | None = Query(default=None, ge=1, le=5000),
) -> dict[str, Any]:
    run_payload = await _load_authorized_run_payload(
        runtime=runtime,
        chat=chat,
        principal=principal,
        run_id=run_id,
    )
    list_events = _journal_method(runtime, "list_events")
    events = await list_events(run_id, event=event, limit=limit)
    return {
        "run_id": run_id,
        "thread_id": run_payload["thread_id"],
        "events": [
            _json_safe(item.to_dict() if hasattr(item, "to_dict") else item) for item in events
        ],
    }
