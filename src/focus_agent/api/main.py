from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncIterator, Sequence
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from focus_agent.core.request_context import RequestContext
from focus_agent.core.types import ConversationRecord
from focus_agent.security.tokens import Principal, create_access_token
from focus_agent.config import Settings
from focus_agent.core.branching import MergeDecision
from focus_agent.engine.runtime import AppRuntime, create_runtime
from focus_agent.observability.trajectory_actions import (
    build_promoted_dataset_payload,
    load_turn_export,
    run_replay_for_turn,
)
from focus_agent.repositories.postgres_trajectory_repository import (
    PostgresTrajectoryRepository,
    TrajectoryTurnQuery,
)
from focus_agent.services.chat import ChatService, ConcurrentTurnError
from focus_agent.web.frontend_app import (
    build_frontend_dev_server_redirect_url,
    render_frontend_entry_html,
    resolve_frontend_dev_server_url,
    resolve_frontend_dist_dir,
)

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
    TrajectoryPromotionRequest,
    TrajectoryPromotionResponse,
    TrajectoryReplayComparisonResponse,
    TrajectoryReplayCaseResponse,
    TrajectoryReplayRequest,
    TrajectoryReplayResponse,
    TrajectoryReplayResultResponse,
    ThreadStateResponse,
    TokenResponse,
    TrajectoryStatsBucketResponse,
    TrajectoryStatsOverviewResponse,
    TrajectoryStepResponse,
    TrajectoryTurnDetailEnvelopeResponse,
    TrajectoryTurnDetailResponse,
    TrajectoryTurnListResponse,
    TrajectoryTurnStatsEnvelopeResponse,
    TrajectoryTurnStatsResponse,
    TrajectoryTurnSummaryResponse,
    UpdateBranchNameRequest,
    UpdateConversationRequest,
)
from .deps import get_app_runtime, get_chat_service, get_current_principal
from .errors import register_exception_handlers
from .middleware import configure_middleware
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


def _as_scalar_or_sequence(values: Sequence[str] | None) -> str | list[str] | None:
    if not values:
        return None
    normalized = [str(value).strip() for value in values if str(value).strip()]
    if not normalized:
        return None
    if len(normalized) == 1:
        return normalized[0]
    return normalized


def _trajectory_query_from_request(
    *,
    thread_id: str | None = None,
    root_thread_id: str | None = None,
    parent_thread_id: str | None = None,
    branch_id: str | None = None,
    branch_role: Sequence[str] | None = None,
    status: Sequence[str] | None = None,
    scene: Sequence[str] | None = None,
    kind: Sequence[str] | None = None,
    tool: Sequence[str] | None = None,
    model: Sequence[str] | None = None,
    fallback_used: bool | None = None,
    cache_hit: bool | None = None,
    has_error: bool | None = None,
    started_after: datetime | None = None,
    started_before: datetime | None = None,
    min_latency_ms: float | None = None,
    max_latency_ms: float | None = None,
    min_tool_calls: int | None = None,
    max_tool_calls: int | None = None,
    limit: int | None = None,
    offset: int = 0,
    newest_first: bool = True,
) -> TrajectoryTurnQuery:
    return TrajectoryTurnQuery(
        thread_id=thread_id,
        root_thread_id=root_thread_id,
        parent_thread_id=parent_thread_id,
        branch_id=branch_id,
        branch_role=_as_scalar_or_sequence(branch_role),
        status=_as_scalar_or_sequence(status),
        scene=_as_scalar_or_sequence(scene),
        kind=_as_scalar_or_sequence(kind),
        tool=_as_scalar_or_sequence(tool),
        selected_model=_as_scalar_or_sequence(model),
        fallback_used=fallback_used,
        cache_hit=cache_hit,
        has_error=has_error,
        since=started_after,
        until=started_before,
        min_latency_ms=min_latency_ms,
        max_latency_ms=max_latency_ms,
        min_tool_calls=min_tool_calls,
        max_tool_calls=max_tool_calls,
        limit=limit,
        offset=offset,
        newest_first=newest_first,
    )


def _get_trajectory_repository(runtime: AppRuntime) -> PostgresTrajectoryRepository | Any:
    candidate = runtime.trajectory_recorder
    required_methods = ("list_turns", "get_turn", "list_steps_by_turn_ids", "get_turn_stats")
    if candidate is not None and all(callable(getattr(candidate, name, None)) for name in required_methods):
        return candidate
    if runtime.settings.database_uri:
        return PostgresTrajectoryRepository(runtime.settings.database_uri)
    raise HTTPException(
        status_code=503,
        detail=(
            "Trajectory observability requires a configured Postgres database "
            "or an initialized trajectory recorder."
        ),
    )


def _build_trajectory_summary_response(item: dict[str, Any]) -> TrajectoryTurnSummaryResponse:
    return TrajectoryTurnSummaryResponse.model_validate(item)


def _build_trajectory_detail_response(
    *,
    record: Any,
    step_rows: Sequence[dict[str, Any]],
    created_at: Any = None,
) -> TrajectoryTurnDetailResponse:
    metrics = dict(getattr(record, "metrics", {}) or {})
    payload = {
        "id": str(record.id),
        "schema_version": int(record.schema_version),
        "kind": str(record.kind),
        "status": str(record.status),
        "thread_id": str(record.thread_id),
        "root_thread_id": str(record.root_thread_id),
        "parent_thread_id": record.parent_thread_id,
        "branch_id": record.branch_id,
        "branch_role": record.branch_role,
        "user_id_hash": str(record.user_id_hash),
        "scene": str(record.scene),
        "turn_index": record.turn_index,
        "task_brief": record.task_brief,
        "user_message": record.user_message,
        "answer": record.answer,
        "selected_model": record.selected_model,
        "selected_thinking_mode": record.selected_thinking_mode,
        "plan": record.plan,
        "reflection": record.reflection,
        "plan_meta": dict(getattr(record, "plan_meta", {}) or {}),
        "metrics": metrics,
        "error": record.error,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
        "created_at": created_at,
        "latency_ms": float(metrics.get("latency_ms") or 0.0),
        "tool_calls": int(metrics.get("tool_calls") or 0),
        "llm_calls": int(metrics.get("llm_calls") or 0),
        "cache_hits": int(metrics.get("cache_hits") or 0),
        "fallback_uses": int(metrics.get("fallback_uses") or 0),
        "trajectory": [TrajectoryStepResponse.model_validate(step) for step in step_rows],
    }
    return TrajectoryTurnDetailResponse.model_validate(payload)


def _build_trajectory_stats_response(stats: dict[str, Any]) -> TrajectoryTurnStatsResponse:
    return TrajectoryTurnStatsResponse(
        overview=TrajectoryStatsOverviewResponse.model_validate(stats.get("overview") or {}),
        by_status=[
            TrajectoryStatsBucketResponse.model_validate(item)
            for item in (stats.get("by_status") or [])
        ],
        by_scene=[
            TrajectoryStatsBucketResponse.model_validate(item)
            for item in (stats.get("by_scene") or [])
        ],
        by_branch_role=[
            TrajectoryStatsBucketResponse.model_validate(item)
            for item in (stats.get("by_branch_role") or [])
        ],
        by_tool=[
            TrajectoryStatsBucketResponse.model_validate(item)
            for item in (stats.get("by_tool") or [])
        ],
    )


def _trajectory_filters_payload(
    *,
    thread_id: str | None = None,
    root_thread_id: str | None = None,
    parent_thread_id: str | None = None,
    branch_id: str | None = None,
    branch_role: Sequence[str] | None = None,
    status: Sequence[str] | None = None,
    scene: Sequence[str] | None = None,
    kind: Sequence[str] | None = None,
    tool: Sequence[str] | None = None,
    model: Sequence[str] | None = None,
    fallback_used: bool | None = None,
    cache_hit: bool | None = None,
    has_error: bool | None = None,
    started_after: datetime | None = None,
    started_before: datetime | None = None,
    min_latency_ms: float | None = None,
    max_latency_ms: float | None = None,
    min_tool_calls: int | None = None,
    max_tool_calls: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if thread_id:
        payload["thread_id"] = thread_id
    if root_thread_id:
        payload["root_thread_id"] = root_thread_id
    if parent_thread_id:
        payload["parent_thread_id"] = parent_thread_id
    if branch_id:
        payload["branch_id"] = branch_id
    if branch_role:
        payload["branch_role"] = list(branch_role)
    if status:
        payload["status"] = list(status)
    if scene:
        payload["scene"] = list(scene)
    if kind:
        payload["kind"] = list(kind)
    if tool:
        payload["tool"] = list(tool)
    if model:
        payload["model"] = list(model)
    if fallback_used is not None:
        payload["fallback_used"] = fallback_used
    if cache_hit is not None:
        payload["cache_hit"] = cache_hit
    if has_error is not None:
        payload["has_error"] = has_error
    if started_after is not None:
        payload["started_after"] = started_after.isoformat()
    if started_before is not None:
        payload["started_before"] = started_before.isoformat()
    if min_latency_ms is not None:
        payload["min_latency_ms"] = min_latency_ms
    if max_latency_ms is not None:
        payload["max_latency_ms"] = max_latency_ms
    if min_tool_calls is not None:
        payload["min_tool_calls"] = min_tool_calls
    if max_tool_calls is not None:
        payload["max_tool_calls"] = max_tool_calls
    return payload


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


def _render_frontend_or_raise(*, settings: Settings) -> str:
    try:
        return render_frontend_entry_html(settings=settings)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Frontend build is missing. Run `pnpm web:build` or `make web-build` "
                "before opening /app."
            ),
        ) from exc


def _frontend_dev_redirect(
    *,
    settings: Settings,
    path: str = "",
    query: str = "",
) -> RedirectResponse | None:
    target = build_frontend_dev_server_redirect_url(settings=settings, path=path, query=query)
    if target is None:
        return None
    return RedirectResponse(url=target, status_code=307)


def create_app() -> FastAPI:
    settings = Settings.from_env()
    app = FastAPI(
        title='focus-agent',
        version=settings.app_version,
        description='Long-dialogue research agent API with branchable conversations.',
        lifespan=app_lifespan,
    )

    configure_middleware(app, settings=settings)
    register_exception_handlers(app)

    frontend_dist_dir = resolve_frontend_dist_dir(settings)
    frontend_assets_dir = frontend_dist_dir / "assets"
    frontend_dev_server_url = resolve_frontend_dev_server_url(settings)
    if frontend_dev_server_url is None and frontend_assets_dir.exists():
        app.mount("/app/assets", StaticFiles(directory=frontend_assets_dir), name="frontend_assets")

    @app.get('/healthz')
    def health_check() -> dict[str, str]:
        return {'status': 'ok'}

    @app.get('/app', response_class=HTMLResponse)
    def render_chat_app_page(request: Request):
        redirect = _frontend_dev_redirect(settings=settings, query=request.url.query)
        if redirect is not None:
            return redirect
        return _render_frontend_or_raise(settings=settings)

    @app.get('/app/zh', response_class=HTMLResponse)
    def redirect_chinese_chat_app() -> RedirectResponse:
        redirect = _frontend_dev_redirect(settings=settings, query="lang=zh")
        if redirect is not None:
            return redirect
        return RedirectResponse(url='/app?lang=zh', status_code=307)

    @app.get('/app/{path:path}', response_class=HTMLResponse)
    def render_chat_app_subpath(path: str, request: Request):
        redirect = _frontend_dev_redirect(settings=settings, path=path, query=request.url.query)
        if redirect is not None:
            return redirect
        return _render_frontend_or_raise(settings=settings)

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

    @app.get('/v1/observability/trajectory', response_model=TrajectoryTurnListResponse)
    def list_trajectory_turns(
        thread_id: str | None = None,
        root_thread_id: str | None = None,
        parent_thread_id: str | None = None,
        branch_id: str | None = None,
        branch_role: list[str] | None = Query(default=None),
        status: list[str] | None = Query(default=None),
        scene: list[str] | None = Query(default=None),
        kind: list[str] | None = Query(default=None),
        tool: list[str] | None = Query(default=None),
        model: list[str] | None = Query(default=None, alias='model'),
        fallback_used: bool | None = None,
        cache_hit: bool | None = None,
        has_error: bool | None = None,
        started_after: datetime | None = None,
        started_before: datetime | None = None,
        min_latency_ms: float | None = None,
        max_latency_ms: float | None = None,
        min_tool_calls: int | None = None,
        max_tool_calls: int | None = None,
        limit: int = Query(default=100, ge=0),
        offset: int = Query(default=0, ge=0),
        newest_first: bool = True,
        principal: Principal = Depends(get_current_principal),
        runtime: AppRuntime = Depends(get_app_runtime),
    ) -> TrajectoryTurnListResponse:
        del principal
        repo = _get_trajectory_repository(runtime)
        filters = _trajectory_filters_payload(
            thread_id=thread_id,
            root_thread_id=root_thread_id,
            parent_thread_id=parent_thread_id,
            branch_id=branch_id,
            branch_role=branch_role,
            status=status,
            scene=scene,
            kind=kind,
            tool=tool,
            model=model,
            fallback_used=fallback_used,
            cache_hit=cache_hit,
            has_error=has_error,
            started_after=started_after,
            started_before=started_before,
            min_latency_ms=min_latency_ms,
            max_latency_ms=max_latency_ms,
            min_tool_calls=min_tool_calls,
            max_tool_calls=max_tool_calls,
        )
        query = _trajectory_query_from_request(
            thread_id=thread_id,
            root_thread_id=root_thread_id,
            parent_thread_id=parent_thread_id,
            branch_id=branch_id,
            branch_role=branch_role,
            status=status,
            scene=scene,
            kind=kind,
            tool=tool,
            model=model,
            fallback_used=fallback_used,
            cache_hit=cache_hit,
            has_error=has_error,
            started_after=started_after,
            started_before=started_before,
            min_latency_ms=min_latency_ms,
            max_latency_ms=max_latency_ms,
            min_tool_calls=min_tool_calls,
            max_tool_calls=max_tool_calls,
            limit=limit,
            offset=offset,
            newest_first=newest_first,
        )
        items = [_build_trajectory_summary_response(item) for item in repo.list_turns(query)]
        return TrajectoryTurnListResponse(
            items=items,
            count=len(items),
            filters=filters,
            limit=limit,
            offset=offset,
        )

    @app.get('/v1/observability/trajectory/stats', response_model=TrajectoryTurnStatsEnvelopeResponse)
    def get_trajectory_turn_stats(
        thread_id: str | None = None,
        root_thread_id: str | None = None,
        parent_thread_id: str | None = None,
        branch_id: str | None = None,
        branch_role: list[str] | None = Query(default=None),
        status: list[str] | None = Query(default=None),
        scene: list[str] | None = Query(default=None),
        kind: list[str] | None = Query(default=None),
        tool: list[str] | None = Query(default=None),
        model: list[str] | None = Query(default=None, alias='model'),
        fallback_used: bool | None = None,
        cache_hit: bool | None = None,
        has_error: bool | None = None,
        started_after: datetime | None = None,
        started_before: datetime | None = None,
        min_latency_ms: float | None = None,
        max_latency_ms: float | None = None,
        min_tool_calls: int | None = None,
        max_tool_calls: int | None = None,
        newest_first: bool = True,
        principal: Principal = Depends(get_current_principal),
        runtime: AppRuntime = Depends(get_app_runtime),
    ) -> TrajectoryTurnStatsEnvelopeResponse:
        del principal
        repo = _get_trajectory_repository(runtime)
        filters = _trajectory_filters_payload(
            thread_id=thread_id,
            root_thread_id=root_thread_id,
            parent_thread_id=parent_thread_id,
            branch_id=branch_id,
            branch_role=branch_role,
            status=status,
            scene=scene,
            kind=kind,
            tool=tool,
            model=model,
            fallback_used=fallback_used,
            cache_hit=cache_hit,
            has_error=has_error,
            started_after=started_after,
            started_before=started_before,
            min_latency_ms=min_latency_ms,
            max_latency_ms=max_latency_ms,
            min_tool_calls=min_tool_calls,
            max_tool_calls=max_tool_calls,
        )
        query = _trajectory_query_from_request(
            thread_id=thread_id,
            root_thread_id=root_thread_id,
            parent_thread_id=parent_thread_id,
            branch_id=branch_id,
            branch_role=branch_role,
            status=status,
            scene=scene,
            kind=kind,
            tool=tool,
            model=model,
            fallback_used=fallback_used,
            cache_hit=cache_hit,
            has_error=has_error,
            started_after=started_after,
            started_before=started_before,
            min_latency_ms=min_latency_ms,
            max_latency_ms=max_latency_ms,
            min_tool_calls=min_tool_calls,
            max_tool_calls=max_tool_calls,
            limit=None,
            newest_first=newest_first,
        )
        return TrajectoryTurnStatsEnvelopeResponse(
            filters=filters,
            stats=_build_trajectory_stats_response(repo.get_turn_stats(query)),
        )

    @app.get('/v1/observability/trajectory/{turn_id}', response_model=TrajectoryTurnDetailEnvelopeResponse)
    def get_trajectory_turn_detail(
        turn_id: str,
        principal: Principal = Depends(get_current_principal),
        runtime: AppRuntime = Depends(get_app_runtime),
    ) -> TrajectoryTurnDetailEnvelopeResponse:
        del principal
        repo = _get_trajectory_repository(runtime)
        record = repo.get_turn(turn_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f'Trajectory turn not found: {turn_id}')

        created_at = None
        summary_rows = repo.list_turns(TrajectoryTurnQuery(turn_ids=[turn_id], limit=1))
        if summary_rows:
            created_at = summary_rows[0].get("created_at")

        step_rows = repo.list_steps_by_turn_ids([turn_id]).get(turn_id, [])
        return TrajectoryTurnDetailEnvelopeResponse(
            item=_build_trajectory_detail_response(
                record=record,
                step_rows=step_rows,
                created_at=created_at,
            )
        )

    @app.post('/v1/observability/trajectory/{turn_id}/replay', response_model=TrajectoryReplayResponse)
    def replay_trajectory_turn(
        turn_id: str,
        payload: TrajectoryReplayRequest,
        principal: Principal = Depends(get_current_principal),
        runtime: AppRuntime = Depends(get_app_runtime),
    ) -> TrajectoryReplayResponse:
        del principal
        repo = _get_trajectory_repository(runtime)
        record = load_turn_export(repo, turn_id=turn_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f'Trajectory turn not found: {turn_id}')
        try:
            promoted = build_promoted_dataset_payload(
                record,
                case_id_prefix=payload.case_id_prefix,
                copy_tool_trajectory=payload.copy_tool_trajectory,
                copy_answer_substring=payload.copy_answer_substring,
                answer_substring_chars=payload.answer_substring_chars,
            )
            result = run_replay_for_turn(
                record,
                settings=runtime.settings,
                model=payload.model,
                case_id_prefix=payload.case_id_prefix,
                copy_tool_trajectory=payload.copy_tool_trajectory,
                copy_answer_substring=payload.copy_answer_substring,
                answer_substring_chars=payload.answer_substring_chars,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return TrajectoryReplayResponse(
            source_turn_id=result["source_turn_id"],
            model_used=payload.model or runtime.settings.model,
            replay_case=TrajectoryReplayCaseResponse.model_validate(promoted["dataset_record"]),
            replay_case_jsonl=str(promoted["jsonl"]),
            replay_result=TrajectoryReplayResultResponse.model_validate(result["replay_result"]),
            comparison=TrajectoryReplayComparisonResponse.model_validate(result["comparison"]),
        )

    @app.post('/v1/observability/trajectory/{turn_id}/promote', response_model=TrajectoryPromotionResponse)
    def promote_trajectory_turn(
        turn_id: str,
        payload: TrajectoryPromotionRequest,
        principal: Principal = Depends(get_current_principal),
        runtime: AppRuntime = Depends(get_app_runtime),
    ) -> TrajectoryPromotionResponse:
        del principal
        repo = _get_trajectory_repository(runtime)
        record = load_turn_export(repo, turn_id=turn_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f'Trajectory turn not found: {turn_id}')
        try:
            result = build_promoted_dataset_payload(
                record,
                case_id_prefix=payload.case_id_prefix,
                copy_tool_trajectory=payload.copy_tool_trajectory,
                copy_answer_substring=payload.copy_answer_substring,
                answer_substring_chars=payload.answer_substring_chars,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return TrajectoryPromotionResponse.model_validate(result)

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
        except ConcurrentTurnError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
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
        except ConcurrentTurnError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
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
                language=payload.language,
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
