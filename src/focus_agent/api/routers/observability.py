from __future__ import annotations

# ruff: noqa: F403, F405
from ..route_helpers import *

router = APIRouter()


def _action_helper(name: str):
    from focus_agent.api import main as api_main

    return getattr(api_main, name)


@router.get('/v1/observability/overview', response_model=ObservabilityOverviewResponse)
def get_observability_overview(
    request_id: str | None = None,
    trace_id: str | None = None,
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
) -> ObservabilityOverviewResponse:
    del principal
    runtime_status = _build_runtime_readiness(runtime)
    filters = _trajectory_filters_payload(
        request_id=request_id,
        trace_id=trace_id,
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
        request_id=request_id,
        trace_id=trace_id,
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
    repo = _maybe_get_trajectory_repository(runtime)
    trajectory_available = False
    trajectory_error: str | None = None
    stats = TrajectoryTurnStatsResponse()
    if repo is not None:
        try:
            stats = _build_trajectory_stats_response(repo.get_turn_stats(query))
        except Exception as exc:  # noqa: BLE001
            trajectory_error = str(exc)
        else:
            trajectory_available = True
    return ObservabilityOverviewResponse(
        generated_at=datetime.now(timezone.utc),
        filters=filters,
        runtime=runtime_status,
        trajectory_available=trajectory_available,
        trajectory_error=trajectory_error,
        stats=stats,
    )

@router.get('/v1/observability/trajectory', response_model=TrajectoryTurnListResponse)
def list_trajectory_turns(
    request_id: str | None = None,
    trace_id: str | None = None,
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
        request_id=request_id,
        trace_id=trace_id,
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
        request_id=request_id,
        trace_id=trace_id,
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

@router.get('/v1/observability/trajectory/stats', response_model=TrajectoryTurnStatsEnvelopeResponse)
def get_trajectory_turn_stats(
    request_id: str | None = None,
    trace_id: str | None = None,
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
        request_id=request_id,
        trace_id=trace_id,
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
        request_id=request_id,
        trace_id=trace_id,
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

@router.post(
    '/v1/observability/trajectory/batch/promote-preview',
    response_model=TrajectoryBatchPromotionPreviewResponse,
)
def promote_trajectory_turn_batch_preview(
    payload: TrajectoryBatchPromotionPreviewRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> TrajectoryBatchPromotionPreviewResponse:
    del principal
    repo = _get_trajectory_repository(runtime)
    filters = _trajectory_filters_from_batch_payload(payload)
    records = _export_trajectory_records(repo, _trajectory_query_from_batch_payload(payload))
    try:
        items = [
            TrajectoryPromotionResponse.model_validate(
                _action_helper("build_promoted_dataset_payload")(
                    record,
                    case_id_prefix=payload.case_id_prefix,
                    copy_tool_trajectory=payload.copy_tool_trajectory,
                    copy_answer_substring=payload.copy_answer_substring,
                    answer_substring_chars=payload.answer_substring_chars,
                )
            )
            for record in records
        ]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TrajectoryBatchPromotionPreviewResponse(
        items=items,
        count=len(items),
        filters=filters,
        limit=payload.limit,
        offset=payload.offset,
        jsonl="\n".join(item.jsonl for item in items),
    )

@router.post(
    '/v1/observability/trajectory/batch/replay-compare',
    response_model=TrajectoryBatchReplayCompareResponse,
)
def replay_trajectory_turn_batch_compare(
    payload: TrajectoryBatchReplayCompareRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> TrajectoryBatchReplayCompareResponse:
    del principal
    repo = _get_trajectory_repository(runtime)
    filters = _trajectory_filters_from_batch_payload(payload)
    records = _export_trajectory_records(repo, _trajectory_query_from_batch_payload(payload))
    results: list[TrajectoryReplayResponse] = []
    try:
        for record in records:
            promoted = _action_helper("build_promoted_dataset_payload")(
                record,
                case_id_prefix=payload.case_id_prefix,
                copy_tool_trajectory=payload.copy_tool_trajectory,
                copy_answer_substring=payload.copy_answer_substring,
                answer_substring_chars=payload.answer_substring_chars,
            )
            replay = _action_helper("run_replay_for_turn")(
                record,
                settings=runtime.settings,
                model=payload.model,
                case_id_prefix=payload.case_id_prefix,
                copy_tool_trajectory=payload.copy_tool_trajectory,
                copy_answer_substring=payload.copy_answer_substring,
                answer_substring_chars=payload.answer_substring_chars,
            )
            results.append(
                TrajectoryReplayResponse(
                    source_turn_id=replay["source_turn_id"],
                    model_used=payload.model or runtime.settings.model,
                    replay_case=TrajectoryReplayCaseResponse.model_validate(promoted["dataset_record"]),
                    replay_case_jsonl=str(promoted["jsonl"]),
                    replay_result=TrajectoryReplayResultResponse.model_validate(replay["replay_result"]),
                    comparison=TrajectoryReplayComparisonResponse.model_validate(replay["comparison"]),
                )
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TrajectoryBatchReplayCompareResponse(
        results=results,
        summary=_build_batch_replay_summary(results),
        filters=filters,
        limit=payload.limit,
        offset=payload.offset,
    )

@router.get('/v1/observability/trajectory/{turn_id}', response_model=TrajectoryTurnDetailEnvelopeResponse)
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

@router.post('/v1/observability/trajectory/{turn_id}/replay', response_model=TrajectoryReplayResponse)
def replay_trajectory_turn(
    turn_id: str,
    payload: TrajectoryReplayRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> TrajectoryReplayResponse:
    del principal
    repo = _get_trajectory_repository(runtime)
    record = _action_helper("load_turn_export")(repo, turn_id=turn_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f'Trajectory turn not found: {turn_id}')
    try:
        promoted = _action_helper("build_promoted_dataset_payload")(
            record,
            case_id_prefix=payload.case_id_prefix,
            copy_tool_trajectory=payload.copy_tool_trajectory,
            copy_answer_substring=payload.copy_answer_substring,
            answer_substring_chars=payload.answer_substring_chars,
        )
        result = _action_helper("run_replay_for_turn")(
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

@router.post('/v1/observability/trajectory/{turn_id}/promote', response_model=TrajectoryPromotionResponse)
def promote_trajectory_turn(
    turn_id: str,
    payload: TrajectoryPromotionRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> TrajectoryPromotionResponse:
    del principal
    repo = _get_trajectory_repository(runtime)
    record = _action_helper("load_turn_export")(repo, turn_id=turn_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f'Trajectory turn not found: {turn_id}')
    try:
        result = _action_helper("build_promoted_dataset_payload")(
            record,
            case_id_prefix=payload.case_id_prefix,
            copy_tool_trajectory=payload.copy_tool_trajectory,
            copy_answer_substring=payload.copy_answer_substring,
            answer_substring_chars=payload.answer_substring_chars,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TrajectoryPromotionResponse.model_validate(result)
