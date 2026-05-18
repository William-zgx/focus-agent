from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TrajectoryStepResponse(BaseModel):
    step_index: int | None = None
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    observation: str = ""
    observation_truncated: bool = False
    duration_ms: float = 0.0
    error: str | None = None
    cache_hit: bool = False
    fallback_used: bool = False
    fallback_group: str | None = None
    parallel_batch_size: int | None = None
    runtime: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class TrajectoryTurnSummaryResponse(BaseModel):
    id: str
    schema_version: int
    kind: str
    status: str
    thread_id: str
    root_thread_id: str
    request_id: str | None = None
    trace_id: str | None = None
    root_span_id: str | None = None
    environment: str | None = None
    deployment: str | None = None
    app_version: str | None = None
    parent_thread_id: str | None = None
    branch_id: str | None = None
    branch_role: str | None = None
    scene: str
    turn_index: int | None = None
    task_brief: str | None = None
    user_message: str | None = None
    answer: str | None = None
    selected_model: str | None = None
    selected_thinking_mode: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    plan_meta: dict[str, Any] = Field(default_factory=dict)
    latency_ms: float = 0.0
    tool_calls: int = 0
    llm_calls: int = 0
    cache_hits: int = 0
    fallback_uses: int = 0


class TrajectoryTurnListResponse(BaseModel):
    items: list[TrajectoryTurnSummaryResponse] = Field(default_factory=list)
    count: int = 0
    filters: dict[str, Any] = Field(default_factory=dict)
    limit: int
    offset: int


class TrajectoryTurnDetailResponse(TrajectoryTurnSummaryResponse):
    user_id_hash: str
    plan: Any = None
    reflection: Any = None
    trajectory: list[TrajectoryStepResponse] = Field(default_factory=list)


class TrajectoryTurnDetailEnvelopeResponse(BaseModel):
    item: TrajectoryTurnDetailResponse | None = None


class TrajectoryStatsOverviewResponse(BaseModel):
    turn_count: int = 0
    succeeded_count: int = 0
    non_succeeded_count: int = 0
    total_tool_calls: int = 0
    total_llm_calls: int = 0
    total_cache_hits: int = 0
    total_fallback_uses: int = 0
    avg_latency_ms: float = 0.0
    max_latency_ms: float = 0.0


class TrajectoryStatsBucketResponse(BaseModel):
    key: str
    turn_count: int | None = None
    step_count: int | None = None
    avg_latency_ms: float | None = None
    cache_hit_steps: int | None = None
    fallback_steps: int | None = None
    avg_duration_ms: float | None = None


class TrajectoryTurnStatsResponse(BaseModel):
    overview: TrajectoryStatsOverviewResponse = Field(
        default_factory=TrajectoryStatsOverviewResponse
    )
    by_status: list[TrajectoryStatsBucketResponse] = Field(default_factory=list)
    by_scene: list[TrajectoryStatsBucketResponse] = Field(default_factory=list)
    by_branch_role: list[TrajectoryStatsBucketResponse] = Field(default_factory=list)
    by_model: list[TrajectoryStatsBucketResponse] = Field(default_factory=list)
    by_day: list[TrajectoryStatsBucketResponse] = Field(default_factory=list)
    by_tool: list[TrajectoryStatsBucketResponse] = Field(default_factory=list)


class TrajectoryTurnStatsEnvelopeResponse(BaseModel):
    filters: dict[str, Any] = Field(default_factory=dict)
    stats: TrajectoryTurnStatsResponse = Field(default_factory=TrajectoryTurnStatsResponse)


class RuntimeComponentStatusResponse(BaseModel):
    name: str
    ready: bool = True
    detail: str | None = None


class RuntimeReadinessResponse(BaseModel):
    status: str = "ok"
    ready: bool = True
    app_version: str | None = None
    environment: str | None = None
    deployment: str | None = None
    checks: list[RuntimeComponentStatusResponse] = Field(default_factory=list)


class ObservabilityOverviewResponse(BaseModel):
    generated_at: datetime
    filters: dict[str, Any] = Field(default_factory=dict)
    runtime: RuntimeReadinessResponse = Field(default_factory=RuntimeReadinessResponse)
    trajectory_available: bool = False
    trajectory_error: str | None = None
    stats: TrajectoryTurnStatsResponse = Field(default_factory=TrajectoryTurnStatsResponse)


class TrajectoryReplayRequest(BaseModel):
    model: str | None = None
    case_id_prefix: str = "traj"
    copy_tool_trajectory: bool = False
    copy_answer_substring: bool = False
    answer_substring_chars: int = Field(default=160, ge=0, le=4000)


class TrajectoryPromotionRequest(BaseModel):
    case_id_prefix: str = "traj"
    copy_tool_trajectory: bool = False
    copy_answer_substring: bool = False
    answer_substring_chars: int = Field(default=160, ge=0, le=4000)


class TrajectoryBatchFilterRequest(BaseModel):
    turn_ids: list[str] = Field(default_factory=list)
    request_id: str | None = None
    trace_id: str | None = None
    thread_id: str | None = None
    root_thread_id: str | None = None
    parent_thread_id: str | None = None
    branch_id: str | None = None
    branch_role: list[str] = Field(default_factory=list)
    status: list[str] = Field(default_factory=list)
    scene: list[str] = Field(default_factory=list)
    kind: list[str] = Field(default_factory=list)
    tool: list[str] = Field(default_factory=list)
    model: list[str] = Field(default_factory=list)
    fallback_used: bool | None = None
    cache_hit: bool | None = None
    has_error: bool | None = None
    started_after: datetime | None = None
    started_before: datetime | None = None
    min_latency_ms: float | None = None
    max_latency_ms: float | None = None
    min_tool_calls: int | None = None
    max_tool_calls: int | None = None
    limit: int = Field(default=100, ge=0)
    offset: int = Field(default=0, ge=0)
    newest_first: bool = True


class TrajectoryBatchPromotionPreviewRequest(TrajectoryBatchFilterRequest):
    case_id_prefix: str = "traj"
    copy_tool_trajectory: bool = False
    copy_answer_substring: bool = False
    answer_substring_chars: int = Field(default=160, ge=0, le=4000)


class TrajectoryBatchReplayCompareRequest(TrajectoryBatchPromotionPreviewRequest):
    model: str | None = None


class TrajectoryEvalCaseResponse(BaseModel):
    id: str
    input: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    scene: str
    skill_hints: list[str] = Field(default_factory=list)
    setup: list[dict[str, str]] = Field(default_factory=list)
    judge: dict[str, Any] = Field(default_factory=dict)
    origin: dict[str, Any] | None = None


class TrajectoryReplayCaseResponse(TrajectoryEvalCaseResponse):
    pass


class TrajectoryJudgeVerdictResponse(BaseModel):
    kind: str
    passed: bool
    reasoning: str = ""
    confidence: float = 1.0
    details: dict[str, Any] = Field(default_factory=dict)


class TrajectoryReplayResultResponse(BaseModel):
    case_id: str
    passed: bool
    answer: str
    verdicts: list[TrajectoryJudgeVerdictResponse] = Field(default_factory=list)
    trajectory: list[TrajectoryStepResponse] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    tags: list[str] = Field(default_factory=list)


class TrajectoryReplayComparisonResponse(BaseModel):
    case_id: str
    trajectory_id: str | None = None
    source_status: str | None = None
    source_failed: bool = False
    replay_passed: bool = False
    replay_error: str | None = None
    source_tools: list[str] = Field(default_factory=list)
    replay_tools: list[str] = Field(default_factory=list)
    tool_path_changed: bool = False
    source_tool_calls: int = 0
    replay_tool_calls: int = 0
    source_latency_ms: float = 0.0
    replay_latency_ms: float = 0.0
    source_fallback_uses: int = 0
    replay_fallback_uses: int = 0
    source_cache_hits: int = 0
    replay_cache_hits: int = 0
    source_answer_preview: str = ""
    replay_answer_preview: str = ""


class TrajectoryReplayResponse(BaseModel):
    source_turn_id: str
    model_used: str
    replay_case: TrajectoryReplayCaseResponse
    replay_case_jsonl: str
    replay_result: TrajectoryReplayResultResponse
    comparison: TrajectoryReplayComparisonResponse = Field(
        default_factory=TrajectoryReplayComparisonResponse
    )


class TrajectoryPromotionResponse(BaseModel):
    source_turn_id: str
    case_id: str
    dataset_record: TrajectoryEvalCaseResponse
    jsonl: str


class TrajectoryBatchPromotionPreviewResponse(BaseModel):
    items: list[TrajectoryPromotionResponse] = Field(default_factory=list)
    count: int = 0
    filters: dict[str, Any] = Field(default_factory=dict)
    limit: int
    offset: int
    jsonl: str = ""


class TrajectoryBatchReplaySummaryResponse(BaseModel):
    total: int = 0
    passed: int = 0
    failed: int = 0
    source_failed: int = 0
    tool_path_changed: int = 0


class TrajectoryBatchReplayCompareResponse(BaseModel):
    results: list[TrajectoryReplayResponse] = Field(default_factory=list)
    summary: TrajectoryBatchReplaySummaryResponse = Field(
        default_factory=TrajectoryBatchReplaySummaryResponse
    )
    filters: dict[str, Any] = Field(default_factory=dict)
    limit: int
    offset: int


__all__ = [
    "TrajectoryStepResponse",
    "TrajectoryTurnSummaryResponse",
    "TrajectoryTurnListResponse",
    "TrajectoryTurnDetailResponse",
    "TrajectoryTurnDetailEnvelopeResponse",
    "TrajectoryStatsOverviewResponse",
    "TrajectoryStatsBucketResponse",
    "TrajectoryTurnStatsResponse",
    "TrajectoryTurnStatsEnvelopeResponse",
    "RuntimeComponentStatusResponse",
    "RuntimeReadinessResponse",
    "ObservabilityOverviewResponse",
    "TrajectoryReplayRequest",
    "TrajectoryPromotionRequest",
    "TrajectoryBatchFilterRequest",
    "TrajectoryBatchPromotionPreviewRequest",
    "TrajectoryBatchReplayCompareRequest",
    "TrajectoryEvalCaseResponse",
    "TrajectoryReplayCaseResponse",
    "TrajectoryJudgeVerdictResponse",
    "TrajectoryReplayResultResponse",
    "TrajectoryReplayComparisonResponse",
    "TrajectoryReplayResponse",
    "TrajectoryPromotionResponse",
    "TrajectoryBatchPromotionPreviewResponse",
    "TrajectoryBatchReplaySummaryResponse",
    "TrajectoryBatchReplayCompareResponse",
]
