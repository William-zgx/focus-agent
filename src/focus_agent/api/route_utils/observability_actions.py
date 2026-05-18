from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from focus_agent.config import Settings
from focus_agent.engine.runtime import AppRuntime

from ..contracts import (
    TrajectoryBatchPromotionPreviewResponse,
    TrajectoryBatchReplayCompareResponse,
    TrajectoryPromotionResponse,
    TrajectoryReplayCaseResponse,
    TrajectoryReplayComparisonResponse,
    TrajectoryReplayResponse,
    TrajectoryReplayResultResponse,
)
from .trajectory import _build_batch_replay_summary


def _promotion_payload_kwargs(payload: Any) -> dict[str, Any]:
    return {
        "case_id_prefix": payload.case_id_prefix,
        "copy_tool_trajectory": payload.copy_tool_trajectory,
        "copy_answer_substring": payload.copy_answer_substring,
        "answer_substring_chars": payload.answer_substring_chars,
    }


def _trajectory_action(name: str):
    from focus_agent.api import main as api_main

    return getattr(api_main, name)


def load_exported_turn(repo: Any, *, turn_id: str) -> dict[str, Any] | None:
    return _trajectory_action("load_turn_export")(repo, turn_id=turn_id)


def build_trajectory_promotion_response(
    record: dict[str, Any],
    *,
    payload: Any,
) -> TrajectoryPromotionResponse:
    return TrajectoryPromotionResponse.model_validate(
        _trajectory_action("build_promoted_dataset_payload")(
            record,
            **_promotion_payload_kwargs(payload),
        )
    )


def build_trajectory_replay_response(
    record: dict[str, Any],
    *,
    payload: Any,
    settings: Settings,
    model_used: str,
) -> TrajectoryReplayResponse:
    promoted = _trajectory_action("build_promoted_dataset_payload")(
        record,
        **_promotion_payload_kwargs(payload),
    )
    replay = _trajectory_action("run_replay_for_turn")(
        record,
        settings=settings,
        model=getattr(payload, "model", None),
        **_promotion_payload_kwargs(payload),
    )
    return TrajectoryReplayResponse(
        source_turn_id=replay["source_turn_id"],
        model_used=model_used,
        replay_case=TrajectoryReplayCaseResponse.model_validate(promoted["dataset_record"]),
        replay_case_jsonl=str(promoted["jsonl"]),
        replay_result=TrajectoryReplayResultResponse.model_validate(replay["replay_result"]),
        comparison=TrajectoryReplayComparisonResponse.model_validate(replay["comparison"]),
    )


def build_batch_promotion_preview_response(
    *,
    records: Sequence[dict[str, Any]],
    payload: Any,
    filters: dict[str, Any],
) -> TrajectoryBatchPromotionPreviewResponse:
    items = [
        build_trajectory_promotion_response(record, payload=payload)
        for record in records
    ]
    return TrajectoryBatchPromotionPreviewResponse(
        items=items,
        count=len(items),
        filters=filters,
        limit=payload.limit,
        offset=payload.offset,
        jsonl="\n".join(item.jsonl for item in items),
    )


def build_batch_replay_compare_response(
    *,
    records: Sequence[dict[str, Any]],
    payload: Any,
    filters: dict[str, Any],
    runtime: AppRuntime,
) -> TrajectoryBatchReplayCompareResponse:
    model_used = payload.model or runtime.settings.model
    results = [
        build_trajectory_replay_response(
            record,
            payload=payload,
            settings=runtime.settings,
            model_used=model_used,
        )
        for record in records
    ]
    return TrajectoryBatchReplayCompareResponse(
        results=results,
        summary=_build_batch_replay_summary(results),
        filters=filters,
        limit=payload.limit,
        offset=payload.offset,
    )


__all__ = [
    "build_batch_promotion_preview_response",
    "build_batch_replay_compare_response",
    "build_trajectory_promotion_response",
    "build_trajectory_replay_response",
    "load_exported_turn",
]
