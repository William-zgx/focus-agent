from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from focus_agent.core.branching import (
    BranchRole,
    MergeProposalOverrides,
    BranchTreeNode,
    ImportedConclusion,
    MergeMode,
    MergeTarget,
)


class ChatTurnRequest(BaseModel):
    thread_id: str
    message: str
    model: str | None = None
    thinking_mode: str | None = None
    skill_hints: list[str] = Field(default_factory=list)
    user_id: str | None = None


class ModelOptionResponse(BaseModel):
    id: str
    provider: str
    provider_label: str
    name: str
    label: str
    is_default: bool = False
    supports_thinking: bool = False
    default_thinking_enabled: bool = False


class ModelCatalogResponse(BaseModel):
    default_model: str
    models: list[ModelOptionResponse] = Field(default_factory=list)


class ConversationSummaryResponse(BaseModel):
    root_thread_id: str
    title: str
    is_archived: bool = False
    archived_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ConversationListResponse(BaseModel):
    conversations: list[ConversationSummaryResponse] = Field(default_factory=list)


class CreateConversationRequest(BaseModel):
    title: str | None = None


class UpdateConversationRequest(BaseModel):
    title: str


class ChatResumeRequest(BaseModel):
    thread_id: str
    resume: Any
    user_id: str | None = None


class ThreadStateResponse(BaseModel):
    thread_id: str
    root_thread_id: str
    assistant_message: str | None = None
    rolling_summary: str = ''
    selected_model: str = ''
    selected_thinking_mode: str = ''
    branch_meta: dict[str, Any] | None = None
    merge_proposal: dict[str, Any] | None = None
    merge_decision: dict[str, Any] | None = None
    merge_queue: list[dict[str, Any]] = Field(default_factory=list)
    active_skill_ids: list[str] = Field(default_factory=list)
    messages: list[dict[str, Any]] = Field(default_factory=list)
    interrupts: list[Any] = Field(default_factory=list)
    trace: dict[str, Any] = Field(default_factory=dict)


class ForkBranchRequest(BaseModel):
    parent_thread_id: str
    branch_name: str | None = None
    name_source: str | None = None
    branch_role: BranchRole = BranchRole.EXPLORE_ALTERNATIVES
    fork_checkpoint_id: str | None = None
    language: Literal["en", "zh"] | None = None
    user_id: str | None = None


class UpdateBranchNameRequest(BaseModel):
    branch_name: str


class PrepareMergeProposalRequest(BaseModel):
    user_id: str | None = None


class ApplyMergeDecisionRequest(BaseModel):
    approved: bool = True
    mode: MergeMode = MergeMode.SUMMARY_ONLY
    target: MergeTarget = MergeTarget.RETURN_THREAD
    rationale: str | None = None
    selected_artifacts: list[str] = Field(default_factory=list)
    proposal_overrides: MergeProposalOverrides | None = None
    user_id: str | None = None


class ApplyMergeDecisionResponse(BaseModel):
    imported: ImportedConclusion | None = None


class BranchTreeResponse(BaseModel):
    root: BranchTreeNode
    archived_branches: list[BranchTreeNode] = Field(default_factory=list)


class DemoTokenRequest(BaseModel):
    user_id: str = 'researcher-1'
    tenant_id: str | None = None
    scopes: list[str] = Field(default_factory=lambda: ['chat', 'branches'])


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = 'bearer'
    expires_in_seconds: int
    issuer: str


class PrincipalResponse(BaseModel):
    user_id: str
    tenant_id: str | None = None
    scopes: list[str] = Field(default_factory=list)
    auth_enabled: bool = True


class TrajectoryStepResponse(BaseModel):
    step_index: int | None = None
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    observation: str = ''
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
    overview: TrajectoryStatsOverviewResponse = Field(default_factory=TrajectoryStatsOverviewResponse)
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
    reasoning: str = ''
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
    source_answer_preview: str = ''
    replay_answer_preview: str = ''


class TrajectoryReplayResponse(BaseModel):
    source_turn_id: str
    model_used: str
    replay_case: TrajectoryReplayCaseResponse
    replay_case_jsonl: str
    replay_result: TrajectoryReplayResultResponse
    comparison: TrajectoryReplayComparisonResponse = Field(default_factory=TrajectoryReplayComparisonResponse)


class TrajectoryPromotionResponse(BaseModel):
    source_turn_id: str
    case_id: str
    dataset_record: TrajectoryEvalCaseResponse
    jsonl: str


__all__ = [
    "ApplyMergeDecisionRequest",
    "ApplyMergeDecisionResponse",
    "BranchTreeResponse",
    "ChatResumeRequest",
    "ChatTurnRequest",
    "ConversationListResponse",
    "ConversationSummaryResponse",
    "CreateConversationRequest",
    "DemoTokenRequest",
    "ForkBranchRequest",
    "ModelCatalogResponse",
    "ModelOptionResponse",
    "ObservabilityOverviewResponse",
    "PrepareMergeProposalRequest",
    "PrincipalResponse",
    "RuntimeComponentStatusResponse",
    "RuntimeReadinessResponse",
    "TrajectoryEvalCaseResponse",
    "TrajectoryJudgeVerdictResponse",
    "TrajectoryStatsBucketResponse",
    "TrajectoryStatsOverviewResponse",
    "TrajectoryPromotionRequest",
    "TrajectoryPromotionResponse",
    "TrajectoryReplayComparisonResponse",
    "TrajectoryReplayCaseResponse",
    "TrajectoryReplayRequest",
    "TrajectoryReplayResponse",
    "TrajectoryReplayResultResponse",
    "TrajectoryStepResponse",
    "TrajectoryTurnDetailEnvelopeResponse",
    "TrajectoryTurnDetailResponse",
    "TrajectoryTurnListResponse",
    "TrajectoryTurnStatsEnvelopeResponse",
    "TrajectoryTurnStatsResponse",
    "TrajectoryTurnSummaryResponse",
    "ThreadStateResponse",
    "TokenResponse",
    "UpdateBranchNameRequest",
    "UpdateConversationRequest",
]
