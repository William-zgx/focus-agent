from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from focus_agent.engine.runtime import AppRuntime
from focus_agent.security.tokens import Principal
from focus_agent.services.attention import AttentionReviewConflictError, AttentionService
from focus_agent.services.chat import ChatService, ThreadStateUnavailableError

from ..contracts import AttentionCursor, AttentionReviewRequest, AttentionSnapshot
from ..deps import get_app_runtime, get_chat_service, get_current_principal
from ..route_helpers import run_sync_route_call
from ..route_utils.service_errors import PERMISSION_ERROR_RULE, map_service_errors

router = APIRouter()


async def _thread_state(
    *,
    request: Request,
    chat: ChatService,
    principal: Principal,
    thread_id: str,
):
    return await run_sync_route_call(
        chat.get_thread_state,
        thread_id=thread_id,
        user_id=principal.user_id,
        request_id=getattr(request.state, "request_id", None),
    )


@router.get(
    "/v1/threads/{thread_id:path}/attention",
    response_model=AttentionSnapshot,
    responses={403: {"description": "Forbidden"}, 503: {"description": "Thread state unavailable"}},
)
async def get_thread_attention(
    thread_id: str,
    request: Request,
    chat: ChatService = Depends(get_chat_service),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AttentionSnapshot:
    service = AttentionService(runtime.store)
    with map_service_errors(rules=(PERMISSION_ERROR_RULE, (ThreadStateUnavailableError, 503))):
        state = await _thread_state(
            request=request,
            chat=chat,
            principal=principal,
            thread_id=thread_id,
        )
        return await run_sync_route_call(
            service.get_snapshot,
            tenant_id=principal.tenant_id or "",
            user_id=principal.user_id,
            thread_id=thread_id,
            state=state,
        )


@router.post(
    "/v1/threads/{thread_id:path}/attention/reviewed",
    response_model=AttentionCursor,
    responses={
        403: {"description": "Forbidden"},
        409: {"description": "Presented cursor conflicts with current thread state"},
        503: {"description": "Thread state unavailable"},
    },
)
async def review_thread_attention(
    thread_id: str,
    payload: AttentionReviewRequest,
    request: Request,
    chat: ChatService = Depends(get_chat_service),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AttentionCursor:
    service = AttentionService(runtime.store)
    with map_service_errors(
        rules=(
            PERMISSION_ERROR_RULE,
            (ThreadStateUnavailableError, 503),
            (AttentionReviewConflictError, 409),
        )
    ):
        state = await _thread_state(
            request=request,
            chat=chat,
            principal=principal,
            thread_id=thread_id,
        )
        return await run_sync_route_call(
            service.review,
            tenant_id=principal.tenant_id or "",
            user_id=principal.user_id,
            thread_id=thread_id,
            state=state,
            presented_cursor=payload.cursor,
        )


__all__ = ["router"]
