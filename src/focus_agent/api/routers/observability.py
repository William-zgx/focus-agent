from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException

from focus_agent.engine.runtime import AppRuntime
from focus_agent.security.tokens import Principal

from ..contracts import (
    ObservabilityOverviewResponse,
    TrajectoryBatchPromotionPreviewRequest,
    TrajectoryBatchPromotionPreviewResponse,
    TrajectoryBatchReplayCompareRequest,
    TrajectoryBatchReplayCompareResponse,
    TrajectoryPromotionRequest,
    TrajectoryPromotionResponse,
    TrajectoryReplayRequest,
    TrajectoryReplayResponse,
    TrajectoryTurnDetailEnvelopeResponse,
    TrajectoryTurnListResponse,
    TrajectoryTurnStatsEnvelopeResponse,
    TrajectoryTurnStatsResponse,
)
from ..deps import get_app_runtime, get_current_principal
from ..route_utils.observability_actions import (
    build_batch_promotion_preview_response,
    build_batch_replay_compare_response,
    build_trajectory_promotion_response,
    build_trajectory_replay_response,
    load_exported_turn,
)
from ..route_utils.observability_filters import (
    ObservabilityTrajectoryParams,
    observability_trajectory_list_params,
    observability_trajectory_params,
)
from ..route_utils.readiness import _build_runtime_readiness
from ..route_utils.trajectory import (
    TrajectoryTurnQuery,
    _build_trajectory_detail_response,
    _build_trajectory_stats_response,
    _build_trajectory_summary_response,
    _export_trajectory_records,
    _get_trajectory_repository,
    _maybe_get_trajectory_repository,
    _trajectory_filters_from_batch_payload,
    _trajectory_query_from_batch_payload,
)

router = APIRouter()


@router.get("/v1/observability/overview", response_model=ObservabilityOverviewResponse)
def get_observability_overview(
    trajectory_params: ObservabilityTrajectoryParams = Depends(observability_trajectory_params),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> ObservabilityOverviewResponse:
    del principal
    runtime_status = _build_runtime_readiness(runtime)
    filters = trajectory_params.payload()
    query = trajectory_params.query()
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
        generated_at=datetime.now(UTC),
        filters=filters,
        runtime=runtime_status,
        trajectory_available=trajectory_available,
        trajectory_error=trajectory_error,
        stats=stats,
    )


@router.get("/v1/observability/trajectory", response_model=TrajectoryTurnListResponse)
def list_trajectory_turns(
    trajectory_params: ObservabilityTrajectoryParams = Depends(
        observability_trajectory_list_params
    ),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> TrajectoryTurnListResponse:
    del principal
    repo = _get_trajectory_repository(runtime)
    filters = trajectory_params.payload()
    query = trajectory_params.query()
    items = [_build_trajectory_summary_response(item) for item in repo.list_turns(query)]
    return TrajectoryTurnListResponse(
        items=items,
        count=len(items),
        filters=filters,
        limit=trajectory_params.limit if trajectory_params.limit is not None else 0,
        offset=trajectory_params.offset,
    )


@router.get(
    "/v1/observability/trajectory/stats", response_model=TrajectoryTurnStatsEnvelopeResponse
)
def get_trajectory_turn_stats(
    trajectory_params: ObservabilityTrajectoryParams = Depends(observability_trajectory_params),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> TrajectoryTurnStatsEnvelopeResponse:
    del principal
    repo = _get_trajectory_repository(runtime)
    filters = trajectory_params.payload()
    query = trajectory_params.query()
    return TrajectoryTurnStatsEnvelopeResponse(
        filters=filters,
        stats=_build_trajectory_stats_response(repo.get_turn_stats(query)),
    )


@router.post(
    "/v1/observability/trajectory/batch/promote-preview",
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
        return build_batch_promotion_preview_response(
            records=records,
            payload=payload,
            filters=filters,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/v1/observability/trajectory/batch/replay-compare",
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
    try:
        return build_batch_replay_compare_response(
            records=records,
            payload=payload,
            filters=filters,
            runtime=runtime,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/v1/observability/trajectory/{turn_id}", response_model=TrajectoryTurnDetailEnvelopeResponse
)
def get_trajectory_turn_detail(
    turn_id: str,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> TrajectoryTurnDetailEnvelopeResponse:
    del principal
    repo = _get_trajectory_repository(runtime)
    record = repo.get_turn(turn_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Trajectory turn not found: {turn_id}")

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


@router.post(
    "/v1/observability/trajectory/{turn_id}/replay", response_model=TrajectoryReplayResponse
)
def replay_trajectory_turn(
    turn_id: str,
    payload: TrajectoryReplayRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> TrajectoryReplayResponse:
    del principal
    repo = _get_trajectory_repository(runtime)
    record = load_exported_turn(repo, turn_id=turn_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Trajectory turn not found: {turn_id}")
    try:
        return build_trajectory_replay_response(
            record,
            payload=payload,
            settings=runtime.settings,
            model_used=payload.model or runtime.settings.model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/v1/observability/trajectory/{turn_id}/promote", response_model=TrajectoryPromotionResponse
)
def promote_trajectory_turn(
    turn_id: str,
    payload: TrajectoryPromotionRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> TrajectoryPromotionResponse:
    del principal
    repo = _get_trajectory_repository(runtime)
    record = load_exported_turn(repo, turn_id=turn_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Trajectory turn not found: {turn_id}")
    try:
        return build_trajectory_promotion_response(
            record,
            payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
