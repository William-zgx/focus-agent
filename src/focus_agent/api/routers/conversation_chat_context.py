from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request

from focus_agent.core.token_usage import normalize_token_usage
from focus_agent.core.types import ConversationRecord
from focus_agent.engine.runtime import AppRuntime
from focus_agent.security.tokens import Principal
from focus_agent.services.chat import ChatService, ConcurrentTurnError

from ..contracts import (
    BranchActionExecuteResponse,
    ConversationListResponse,
    ConversationSummaryResponse,
    CreateConversationRequest,
    ThreadContextCompactRequest,
    ThreadContextCompactResponse,
    ThreadContextPreviewRequest,
    ThreadContextPreviewResponse,
    ThreadStateResponse,
    UpdateConversationRequest,
)
from ..deps import get_app_runtime, get_chat_service, get_current_principal
from ..route_utils.conversations import _conversation_response, _list_or_bootstrap_conversations
from ..route_utils.token_usage import _token_usage_for_root_thread

router = APIRouter()


@router.get('/v1/conversations', response_model=ConversationListResponse)
def list_conversations(
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> ConversationListResponse:
    conversations = _list_or_bootstrap_conversations(runtime=runtime, user_id=principal.user_id)
    token_usage_by_root = {
        item.root_thread_id: _token_usage_for_root_thread(runtime=runtime, root_thread_id=item.root_thread_id)
        for item in conversations
    }
    return ConversationListResponse(
        conversations=[
            _conversation_response(item.model_copy(update={"token_usage": token_usage_by_root.get(item.root_thread_id, {})}))
            for item in conversations
        ],
    )

@router.post('/v1/conversations', response_model=ConversationSummaryResponse)
def create_conversation(
    payload: CreateConversationRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> ConversationSummaryResponse:
    existing = _list_or_bootstrap_conversations(runtime=runtime, user_id=principal.user_id)
    requested_title = str(payload.title or '').strip()
    title = requested_title or f"Conversation {len(existing) + 1}"
    root_thread_id = f"{principal.user_id}-{uuid4()}"
    runtime.repo.ensure_thread_owner(
        thread_id=root_thread_id,
        root_thread_id=root_thread_id,
        owner_user_id=principal.user_id,
    )
    record = runtime.repo.create_conversation(
        ConversationRecord(
            root_thread_id=root_thread_id,
            owner_user_id=principal.user_id,
            title=title,
            title_pending_ai=not bool(requested_title),
        )
    )
    return _conversation_response(record.model_copy(update={"token_usage": normalize_token_usage()}))

@router.patch('/v1/conversations/{root_thread_id:path}', response_model=ConversationSummaryResponse)
def update_conversation(
    root_thread_id: str,
    payload: UpdateConversationRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> ConversationSummaryResponse:
    title = str(payload.title or '').strip()
    if not title:
        raise HTTPException(status_code=400, detail='Conversation title cannot be empty.')
    try:
        record = runtime.repo.update_conversation_title(
            root_thread_id=root_thread_id,
            owner_user_id=principal.user_id,
            title=title,
            title_pending_ai=False,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConcurrentTurnError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _conversation_response(
        record.model_copy(
            update={"token_usage": _token_usage_for_root_thread(runtime=runtime, root_thread_id=root_thread_id)}
        )
    )

@router.post('/v1/conversations/{root_thread_id:path}/archive', response_model=ConversationSummaryResponse)
def archive_conversation(
    root_thread_id: str,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> ConversationSummaryResponse:
    try:
        record = runtime.branch_service.archive_conversation(
            root_thread_id=root_thread_id,
            user_id=principal.user_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConcurrentTurnError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _conversation_response(
        record.model_copy(
            update={"token_usage": _token_usage_for_root_thread(runtime=runtime, root_thread_id=root_thread_id)}
        )
    )

@router.post('/v1/conversations/{root_thread_id:path}/activate', response_model=ConversationSummaryResponse)
def activate_conversation(
    root_thread_id: str,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> ConversationSummaryResponse:
    try:
        record = runtime.branch_service.activate_conversation(
            root_thread_id=root_thread_id,
            user_id=principal.user_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConcurrentTurnError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _conversation_response(
        record.model_copy(
            update={"token_usage": _token_usage_for_root_thread(runtime=runtime, root_thread_id=root_thread_id)}
        )
    )

@router.get('/v1/threads/{thread_id:path}', response_model=ThreadStateResponse)
def get_thread_snapshot(
    thread_id: str,
    request: Request,
    chat: ChatService = Depends(get_chat_service),
    principal: Principal = Depends(get_current_principal),
) -> ThreadStateResponse:
    try:
        result = chat.get_thread_state(
            thread_id=thread_id,
            user_id=principal.user_id,
            request_id=getattr(request.state, "request_id", None),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return ThreadStateResponse.model_validate(result)

@router.post('/v1/threads/{thread_id:path}/branch-actions/{action_id}/execute', response_model=BranchActionExecuteResponse)
def execute_thread_branch_action(
    thread_id: str,
    action_id: str,
    request: Request,
    chat: ChatService = Depends(get_chat_service),
    principal: Principal = Depends(get_current_principal),
) -> BranchActionExecuteResponse:
    try:
        result = chat.execute_branch_action(
            thread_id=thread_id,
            action_id=action_id,
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
    return BranchActionExecuteResponse.model_validate(result)

@router.post('/v1/threads/{thread_id:path}/branch-actions/{action_id}/dismiss', response_model=ThreadStateResponse)
def dismiss_thread_branch_action(
    thread_id: str,
    action_id: str,
    request: Request,
    chat: ChatService = Depends(get_chat_service),
    principal: Principal = Depends(get_current_principal),
) -> ThreadStateResponse:
    try:
        result = chat.dismiss_branch_action(
            thread_id=thread_id,
            action_id=action_id,
            user_id=principal.user_id,
            request_id=getattr(request.state, "request_id", None),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ThreadStateResponse.model_validate(result)

@router.post('/v1/threads/{thread_id:path}/context/preview', response_model=ThreadContextPreviewResponse)
def preview_thread_context(
    thread_id: str,
    payload: ThreadContextPreviewRequest,
    chat: ChatService = Depends(get_chat_service),
    principal: Principal = Depends(get_current_principal),
) -> ThreadContextPreviewResponse:
    try:
        result = chat.preview_thread_context(
            thread_id=thread_id,
            user_id=principal.user_id,
            draft_message=payload.draft_message,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return ThreadContextPreviewResponse.model_validate(result)

@router.post('/v1/threads/{thread_id:path}/context/compact', response_model=ThreadContextCompactResponse)
def compact_thread_context(
    thread_id: str,
    payload: ThreadContextCompactRequest,
    chat: ChatService = Depends(get_chat_service),
    principal: Principal = Depends(get_current_principal),
) -> ThreadContextCompactResponse:
    try:
        result = chat.compact_thread_context(
            thread_id=thread_id,
            user_id=principal.user_id,
            trigger=payload.trigger,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConcurrentTurnError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ThreadContextCompactResponse.model_validate(result)
