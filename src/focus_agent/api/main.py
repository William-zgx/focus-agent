from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse

from focus_agent.core.request_context import RequestContext
from focus_agent.core.types import ConversationRecord
from focus_agent.security.tokens import Principal, create_access_token
from focus_agent.config import Settings
from focus_agent.core.branching import MergeDecision
from focus_agent.engine.runtime import AppRuntime, create_runtime
from focus_agent.services.chat import ChatService
from focus_agent.web.app_shell import render_chat_app_html

from .contracts import (
    ApplyMergeDecisionRequest,
    ApplyMergeDecisionResponse,
    BranchTreeResponse,
    ChatResumeRequest,
    ChatTurnRequest,
    ConversationListResponse,
    ConversationSummaryResponse,
    CreateConversationRequest,
    DemoTokenRequest,
    ForkBranchRequest,
    ModelCatalogResponse,
    PrepareMergeProposalRequest,
    PrincipalResponse,
    ThreadStateResponse,
    TokenResponse,
    UpdateBranchNameRequest,
    UpdateConversationRequest,
)
from .deps import get_app_runtime, get_chat_service, get_current_principal
from focus_agent.model_registry import build_model_catalog


def _conversation_response(record: ConversationRecord) -> ConversationSummaryResponse:
    return ConversationSummaryResponse(
        root_thread_id=record.root_thread_id,
        title=record.title,
        is_archived=record.is_archived,
        archived_at=record.archived_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _list_or_bootstrap_conversations(*, runtime: AppRuntime, user_id: str) -> list[ConversationRecord]:
    conversations = runtime.repo.list_conversations(owner_user_id=user_id)
    if conversations:
        return conversations

    default_root_thread_id = f"{user_id}-main"
    runtime.repo.ensure_thread_owner(
        thread_id=default_root_thread_id,
        root_thread_id=default_root_thread_id,
        owner_user_id=user_id,
    )
    runtime.repo.create_conversation(
        ConversationRecord(
            root_thread_id=default_root_thread_id,
            owner_user_id=user_id,
            title="Main",
            title_pending_ai=True,
        )
    )
    return runtime.repo.list_conversations(owner_user_id=user_id)


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    runtime = create_runtime(Settings.from_env())
    app.state.runtime = runtime
    app.state.chat_service = ChatService(runtime)
    try:
        yield
    finally:
        runtime.close()


def _event_stream_response(stream: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(
        stream,
        media_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
        },
    )


def create_app() -> FastAPI:
    app = FastAPI(
        title='focus-agent',
        version=Settings.from_env().app_version,
        description='Long-dialogue research agent API with branchable conversations.',
        lifespan=app_lifespan,
    )

    @app.get('/healthz')
    def health_check() -> dict[str, str]:
        return {'status': 'ok'}

    @app.get('/app', response_class=HTMLResponse)
    def render_chat_app_page(lang: str = "en") -> str:
        return render_chat_app_html(lang)

    @app.get('/app/zh', response_class=HTMLResponse)
    def redirect_chinese_chat_app() -> RedirectResponse:
        return RedirectResponse(url='/app?lang=zh', status_code=307)

    @app.post('/v1/auth/demo-token', response_model=TokenResponse)
    def issue_demo_token(payload: DemoTokenRequest, runtime: AppRuntime = Depends(get_app_runtime)) -> TokenResponse:
        if not runtime.settings.auth_demo_tokens_enabled:
            raise HTTPException(status_code=404, detail='Demo token issuance is disabled.')
        token = create_access_token(
            settings=runtime.settings,
            user_id=payload.user_id,
            tenant_id=payload.tenant_id,
            scopes=payload.scopes,
        )
        return TokenResponse(
            access_token=token,
            expires_in_seconds=runtime.settings.auth_access_token_ttl_seconds,
            issuer=runtime.settings.auth_jwt_issuer,
        )

    @app.get('/v1/auth/me', response_model=PrincipalResponse)
    def get_me(principal: Principal = Depends(get_current_principal), runtime: AppRuntime = Depends(get_app_runtime)) -> PrincipalResponse:
        return PrincipalResponse(
            user_id=principal.user_id,
            tenant_id=principal.tenant_id,
            scopes=list(principal.scopes),
            auth_enabled=runtime.settings.auth_enabled,
        )

    @app.get('/v1/models', response_model=ModelCatalogResponse)
    def list_models(
        principal: Principal = Depends(get_current_principal),
        runtime: AppRuntime = Depends(get_app_runtime),
    ) -> ModelCatalogResponse:
        del principal
        return ModelCatalogResponse(
            default_model=runtime.settings.model,
            models=[
                {
                    "id": item.id,
                    "provider": item.provider,
                    "provider_label": item.provider_label,
                    "name": item.name,
                    "label": item.label,
                    "is_default": item.is_default,
                    "supports_thinking": item.supports_thinking,
                    "default_thinking_enabled": item.default_thinking_enabled,
                }
                for item in build_model_catalog(runtime.settings)
            ],
        )

    @app.get('/v1/conversations', response_model=ConversationListResponse)
    def list_conversations(
        principal: Principal = Depends(get_current_principal),
        runtime: AppRuntime = Depends(get_app_runtime),
    ) -> ConversationListResponse:
        conversations = _list_or_bootstrap_conversations(runtime=runtime, user_id=principal.user_id)
        return ConversationListResponse(
            conversations=[_conversation_response(item) for item in conversations],
        )

    @app.post('/v1/conversations', response_model=ConversationSummaryResponse)
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
        return _conversation_response(record)

    @app.patch('/v1/conversations/{root_thread_id}', response_model=ConversationSummaryResponse)
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
        return _conversation_response(record)

    @app.post('/v1/conversations/{root_thread_id}/archive', response_model=ConversationSummaryResponse)
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
        return _conversation_response(record)

    @app.post('/v1/conversations/{root_thread_id}/activate', response_model=ConversationSummaryResponse)
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
        return _conversation_response(record)

    @app.post('/v1/chat/turns', response_model=ThreadStateResponse)
    def post_chat_turn(
        payload: ChatTurnRequest,
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
                skill_hints=tuple(payload.skill_hints),
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return ThreadStateResponse.model_validate(result)

    @app.post('/v1/chat/turns/stream')
    def stream_chat_turn(
        payload: ChatTurnRequest,
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
                skill_hints=tuple(payload.skill_hints),
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return _event_stream_response(stream)

    @app.post('/v1/chat/resume', response_model=ThreadStateResponse)
    def resume_chat_turn(
        payload: ChatResumeRequest,
        chat: ChatService = Depends(get_chat_service),
        principal: Principal = Depends(get_current_principal),
    ) -> ThreadStateResponse:
        try:
            result = chat.resume(thread_id=payload.thread_id, user_id=principal.user_id, resume=payload.resume)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return ThreadStateResponse.model_validate(result)

    @app.post('/v1/chat/resume/stream')
    def stream_resumed_chat_turn(
        payload: ChatResumeRequest,
        chat: ChatService = Depends(get_chat_service),
        principal: Principal = Depends(get_current_principal),
    ) -> StreamingResponse:
        try:
            stream = chat.stream_resume(thread_id=payload.thread_id, user_id=principal.user_id, resume=payload.resume)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return _event_stream_response(stream)

    @app.get('/v1/threads/{thread_id}', response_model=ThreadStateResponse)
    def get_thread_snapshot(
        thread_id: str,
        chat: ChatService = Depends(get_chat_service),
        principal: Principal = Depends(get_current_principal),
    ) -> ThreadStateResponse:
        try:
            result = chat.get_thread_state(thread_id=thread_id, user_id=principal.user_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return ThreadStateResponse.model_validate(result)

    @app.post('/v1/branches/fork')
    def create_branch(
        payload: ForkBranchRequest,
        runtime: AppRuntime = Depends(get_app_runtime),
        principal: Principal = Depends(get_current_principal),
    ):
        try:
            record = runtime.branch_service.fork_branch(
                parent_thread_id=payload.parent_thread_id,
                user_id=principal.user_id,
                branch_name=payload.branch_name,
                name_source=payload.name_source,
                branch_role=payload.branch_role,
                fork_checkpoint_id=payload.fork_checkpoint_id,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return record.model_dump(mode='json')

    @app.post('/v1/branches/{child_thread_id}/archive')
    def archive_branch_route(
        child_thread_id: str,
        runtime: AppRuntime = Depends(get_app_runtime),
        principal: Principal = Depends(get_current_principal),
    ):
        try:
            record = runtime.branch_service.archive_branch(
                child_thread_id=child_thread_id,
                user_id=principal.user_id,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return record.model_dump(mode='json')

    @app.patch('/v1/branches/{child_thread_id}')
    def rename_branch_route(
        child_thread_id: str,
        payload: UpdateBranchNameRequest,
        runtime: AppRuntime = Depends(get_app_runtime),
        principal: Principal = Depends(get_current_principal),
    ):
        branch_name = str(payload.branch_name or '').strip()
        if not branch_name:
            raise HTTPException(status_code=400, detail='Branch name cannot be empty.')
        try:
            record = runtime.branch_service.rename_branch(
                child_thread_id=child_thread_id,
                user_id=principal.user_id,
                branch_name=branch_name,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return record.model_dump(mode='json')

    @app.post('/v1/branches/{child_thread_id}/activate')
    def activate_branch_route(
        child_thread_id: str,
        runtime: AppRuntime = Depends(get_app_runtime),
        principal: Principal = Depends(get_current_principal),
    ):
        try:
            record = runtime.branch_service.activate_branch(
                child_thread_id=child_thread_id,
                user_id=principal.user_id,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return record.model_dump(mode='json')

    @app.post('/v1/branches/{child_thread_id}/proposal')
    def prepare_branch_merge_proposal(
        child_thread_id: str,
        payload: PrepareMergeProposalRequest,
        runtime: AppRuntime = Depends(get_app_runtime),
        principal: Principal = Depends(get_current_principal),
    ):
        del payload
        try:
            proposal = runtime.branch_service.prepare_merge_proposal(
                child_thread_id=child_thread_id,
                user_id=principal.user_id,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return proposal.model_dump(mode='json')

    @app.post('/v1/branches/{child_thread_id}/merge', response_model=ApplyMergeDecisionResponse)
    def submit_merge_decision(
        child_thread_id: str,
        payload: ApplyMergeDecisionRequest,
        runtime: AppRuntime = Depends(get_app_runtime),
        principal: Principal = Depends(get_current_principal),
    ) -> ApplyMergeDecisionResponse:
        try:
            record = runtime.repo.get_by_child_thread_id(child_thread_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        decision = MergeDecision.model_validate(payload.model_dump(exclude={'user_id'}))
        try:
            imported = runtime.branch_service.apply_merge_decision(
                child_thread_id=child_thread_id,
                decision=decision,
                context=RequestContext(
                    user_id=principal.user_id,
                    root_thread_id=record.root_thread_id,
                ),
                proposal_overrides=payload.proposal_overrides,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return ApplyMergeDecisionResponse(imported=imported)

    @app.get('/v1/branches/tree/{root_thread_id}', response_model=BranchTreeResponse)
    def get_branch_tree_view(
        root_thread_id: str,
        runtime: AppRuntime = Depends(get_app_runtime),
        principal: Principal = Depends(get_current_principal),
    ) -> BranchTreeResponse:
        try:
            root = runtime.branch_service.get_branch_tree(root_thread_id=root_thread_id, user_id=principal.user_id)
            archived_branches = runtime.branch_service.list_archived_branches(
                root_thread_id=root_thread_id,
                user_id=principal.user_id,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return BranchTreeResponse(root=root, archived_branches=archived_branches)

    return app


app = create_app()


__all__ = [
    "app",
    "app_lifespan",
    "create_app",
]
