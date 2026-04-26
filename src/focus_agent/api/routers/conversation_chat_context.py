from __future__ import annotations

# ruff: noqa: F403, F405
from ..route_helpers import *

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
    return _conversation_response(record.model_copy(update={"token_usage": _normalize_token_usage()}))

@router.patch('/v1/conversations/{root_thread_id}', response_model=ConversationSummaryResponse)
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
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _conversation_response(
        record.model_copy(
            update={"token_usage": _token_usage_for_root_thread(runtime=runtime, root_thread_id=root_thread_id)}
        )
    )

@router.post('/v1/conversations/{root_thread_id}/archive', response_model=ConversationSummaryResponse)
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
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _conversation_response(
        record.model_copy(
            update={"token_usage": _token_usage_for_root_thread(runtime=runtime, root_thread_id=root_thread_id)}
        )
    )

@router.post('/v1/conversations/{root_thread_id}/activate', response_model=ConversationSummaryResponse)
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
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _conversation_response(
        record.model_copy(
            update={"token_usage": _token_usage_for_root_thread(runtime=runtime, root_thread_id=root_thread_id)}
        )
    )

@router.post('/v1/chat/turns', response_model=ThreadStateResponse)
def post_chat_turn(
    payload: ChatTurnRequest,
    request: Request,
    chat: ChatService = Depends(get_chat_service),
    principal: Principal = Depends(get_current_principal),
) -> ThreadStateResponse:
    try:
        result = chat.send_message(
            thread_id=payload.thread_id,
            user_id=principal.user_id,
            message=payload.message,
            model=payload.model,
            thinking_mode=payload.thinking_mode,
            request_id=getattr(request.state, "request_id", None),
            skill_hints=tuple(payload.skill_hints),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConcurrentTurnError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ThreadStateResponse.model_validate(result)

@router.post('/v1/chat/turns/stream')
def stream_chat_turn(
    payload: ChatTurnRequest,
    request: Request,
    chat: ChatService = Depends(get_chat_service),
    principal: Principal = Depends(get_current_principal),
) -> StreamingResponse:
    try:
        stream = chat.stream_message(
            thread_id=payload.thread_id,
            user_id=principal.user_id,
            message=payload.message,
            model=payload.model,
            thinking_mode=payload.thinking_mode,
            request_id=getattr(request.state, "request_id", None),
            skill_hints=tuple(payload.skill_hints),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return _event_stream_response(stream)

@router.post('/v1/chat/resume', response_model=ThreadStateResponse)
def resume_chat_turn(
    payload: ChatResumeRequest,
    request: Request,
    chat: ChatService = Depends(get_chat_service),
    principal: Principal = Depends(get_current_principal),
) -> ThreadStateResponse:
    try:
        result = chat.resume(
            thread_id=payload.thread_id,
            user_id=principal.user_id,
            resume=payload.resume,
            request_id=getattr(request.state, "request_id", None),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConcurrentTurnError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ThreadStateResponse.model_validate(result)

@router.post('/v1/chat/resume/stream')
def stream_resumed_chat_turn(
    payload: ChatResumeRequest,
    request: Request,
    chat: ChatService = Depends(get_chat_service),
    principal: Principal = Depends(get_current_principal),
) -> StreamingResponse:
    try:
        stream = chat.stream_resume(
            thread_id=payload.thread_id,
            user_id=principal.user_id,
            resume=payload.resume,
            request_id=getattr(request.state, "request_id", None),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return _event_stream_response(stream)

@router.get('/v1/threads/{thread_id}', response_model=ThreadStateResponse)
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

@router.post('/v1/threads/{thread_id}/context/preview', response_model=ThreadContextPreviewResponse)
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

@router.post('/v1/threads/{thread_id}/context/compact', response_model=ThreadContextCompactResponse)
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
