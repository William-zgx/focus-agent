from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from focus_agent.core.agent_team import (
    AgentTeamArtifactKind,
    AgentTeamMergeBundle,
    AgentTeamMergeDecision,
    AgentTeamRecommendedAction,
    AgentTeamSession,
    AgentTeamTask,
    AgentTeamTaskOutput,
    AgentTeamTaskRole,
    AgentTeamTaskStatus,
)

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


class AgentRolePolicyResponse(BaseModel):
    enabled: bool = False
    default_model: str
    helper_model: str | None = None
    max_parallel_runs: int = 1
    roles: list[str] = Field(default_factory=list)
    role_models: dict[str, str | None] = Field(default_factory=dict)
    fallback_order: list[str] = Field(default_factory=list)


class AgentRoleDryRunRequest(BaseModel):
    message: str
    scene: str = "long_dialog_research"
    skill_hints: list[str] = Field(default_factory=list)
    available_tools: list[str] = Field(default_factory=list)


class AgentRoleDryRunResponse(BaseModel):
    policy: AgentRolePolicyResponse
    plan: dict[str, Any] = Field(default_factory=dict)


class AgentRoleDecisionListResponse(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
    count: int = 0
    trajectory_available: bool = False
    trajectory_error: str | None = None


class AgentCapabilityResponse(BaseModel):
    name: str
    description: str = ""
    toolset: str | None = None
    allowed_roles: list[str] = Field(default_factory=list)
    risk_level: str = "low"
    side_effect: bool = False
    parallel_safe: bool = False
    cacheable: bool = False
    requires_network: bool = False
    requires_workspace_write: bool = False
    requires_approval: bool = False


class AgentCapabilityListResponse(BaseModel):
    items: list[AgentCapabilityResponse] = Field(default_factory=list)
    count: int = 0


class AgentToolRouteRequest(BaseModel):
    role: str = "executor"
    tool_policy: str = "execution"
    available_tools: list[str] = Field(default_factory=list)
    enforce: bool | None = None


class AgentToolRouteResponse(BaseModel):
    plan: dict[str, Any] = Field(default_factory=dict)


class AgentToolRouteDecisionListResponse(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
    count: int = 0
    trajectory_available: bool = False
    trajectory_error: str | None = None


class AgentMemoryCuratorPolicyResponse(BaseModel):
    enabled: bool = False
    auto_promote_on_merge: bool = True
    branch_local_only_until_merge: bool = True
    conflict_strategy: str = "needs_review"


class AgentMemoryCuratorEvaluateRequest(BaseModel):
    root_thread_id: str
    branch_id: str
    branch_name: str = "Branch"
    branch_role: str = "explore_alternatives"
    branch_status: str = "active"
    child_thread_id: str | None = None
    parent_thread_id: str | None = None
    findings: list[dict[str, Any]] = Field(default_factory=list)
    user_id: str | None = None
    auto_promote: bool | None = None


class AgentMemoryCuratorEvaluateResponse(BaseModel):
    decision: dict[str, Any] = Field(default_factory=dict)


class AgentMemoryCuratorDecisionListResponse(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
    count: int = 0
    trajectory_available: bool = False
    trajectory_error: str | None = None


class AgentDelegationPolicyResponse(BaseModel):
    enabled: bool = False
    enforce: bool = False
    max_parallel_runs: int = 1
    default_off_legacy_safe: bool = True


class AgentDelegationPlanRequest(BaseModel):
    message: str
    scene: str = "agent_delegation_console"
    available_tools: list[str] = Field(default_factory=list)


class AgentDelegationPlanResponse(BaseModel):
    policy: AgentDelegationPolicyResponse
    plan: dict[str, Any] = Field(default_factory=dict)


class AgentDelegationRunListResponse(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
    count: int = 0
    trajectory_available: bool = False
    trajectory_error: str | None = None


class AgentModelRouterPolicyResponse(BaseModel):
    enabled: bool = False
    mode: str = "observe"
    default_model: str
    helper_model: str | None = None
    role_models: dict[str, str | None] = Field(default_factory=dict)


class AgentModelRouteRequest(BaseModel):
    role: str = "executor"
    selected_model: str | None = None
    task_text: str = ""
    tool_risk: str = "low"
    context_size: int = 0


class AgentModelRouteResponse(BaseModel):
    decision: dict[str, Any] = Field(default_factory=dict)


class AgentModelRouterDecisionListResponse(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
    count: int = 0
    trajectory_available: bool = False
    trajectory_error: str | None = None


class AgentSelfRepairFailureListResponse(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
    count: int = 0
    trajectory_available: bool = False
    trajectory_error: str | None = None


class AgentSelfRepairPromotePreviewRequest(BaseModel):
    failures: list[dict[str, Any]] = Field(default_factory=list)
    case_id_prefix: str = "agent_delegation"


class AgentSelfRepairPromotePreviewResponse(BaseModel):
    preview: dict[str, Any] = Field(default_factory=dict)


class AgentReviewQueueListResponse(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
    count: int = 0
    trajectory_available: bool = False
    trajectory_error: str | None = None


class AgentReviewQueueDecisionResponse(BaseModel):
    item: dict[str, Any] = Field(default_factory=dict)


class AgentContextPolicyResponse(BaseModel):
    enabled: bool = False
    artifactize_long_observations: bool = False
    role_views_enabled: bool = False
    tokenizer_mode: str = "chars_fallback"
    artifact_min_chars: int = 12000
    default_off_legacy_safe: bool = True


class AgentContextPreviewRequest(BaseModel):
    state: dict[str, Any] = Field(default_factory=dict)
    prompt_mode: str = "explore"
    role: str = "executor"
    assembled_context: str | None = None
    materialize_artifacts: bool = False


class AgentContextPreviewResponse(BaseModel):
    decision: dict[str, Any] = Field(default_factory=dict)


class AgentContextDecisionListResponse(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
    count: int = 0
    trajectory_available: bool = False
    trajectory_error: str | None = None


class AgentContextArtifactListResponse(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
    count: int = 0
    trajectory_available: bool = False
    trajectory_error: str | None = None


class AgentTaskLedgerPolicyResponse(BaseModel):
    enabled: bool = False
    artifact_synthesis_enabled: bool = False
    critic_gate_enabled: bool = False
    critic_gate_enforce: bool = False
    default_off_legacy_safe: bool = True


class AgentTaskLedgerPlanRequest(BaseModel):
    message: str = ""
    delegation_plan: dict[str, Any] = Field(default_factory=dict)


class AgentTaskLedgerPlanResponse(BaseModel):
    policy: AgentTaskLedgerPolicyResponse
    ledger: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    critic_gate_result: dict[str, Any] | None = None
    synthesis_result: dict[str, Any] | None = None


class AgentTaskLedgerRunListResponse(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
    count: int = 0
    trajectory_available: bool = False
    trajectory_error: str | None = None


class AgentArtifactListResponse(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
    count: int = 0
    trajectory_available: bool = False
    trajectory_error: str | None = None


class AgentArtifactSynthesisRequest(BaseModel):
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    critic_gate_result: dict[str, Any] | None = None


class AgentArtifactSynthesisResponse(BaseModel):
    result: dict[str, Any] = Field(default_factory=dict)


class AgentCriticVerdictListResponse(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
    count: int = 0
    trajectory_available: bool = False
    trajectory_error: str | None = None


class AgentCriticEvaluateRequest(BaseModel):
    ledger: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)


class AgentCriticEvaluateResponse(BaseModel):
    result: dict[str, Any] = Field(default_factory=dict)


class ConversationSummaryResponse(BaseModel):
    root_thread_id: str
    title: str
    is_archived: bool = False
    archived_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    token_usage: dict[str, int] = Field(default_factory=dict)


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


class CreateAgentTeamSessionRequest(BaseModel):
    root_thread_id: str
    title: str | None = None
    goal: str


class AgentTeamSessionResponse(BaseModel):
    session: AgentTeamSession


class AgentTeamSessionListResponse(BaseModel):
    sessions: list[AgentTeamSession] = Field(default_factory=list)
    items: list[AgentTeamSession] = Field(default_factory=list)
    count: int = 0


class CreateAgentTeamTaskRequest(BaseModel):
    role: AgentTeamTaskRole
    goal: str
    scope: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    create_branch: bool = True
    auto_fork_branch: bool | None = None
    branch_name: str | None = None
    branch_id: str | None = None
    child_thread_id: str | None = None
    parent_thread_id: str | None = None


class DispatchAgentTeamSessionRequest(BaseModel):
    create_branches: bool = True
    auto_fork_branch: bool | None = None
    parent_thread_id: str | None = None


class UpdateAgentTeamTaskRequest(BaseModel):
    status: AgentTeamTaskStatus | None = None
    goal: str | None = None
    scope: list[str] | None = None
    dependencies: list[str] | None = None
    branch_id: str | None = None
    child_thread_id: str | None = None
    output_artifact_ids: list[str] | None = None
    changed_files: list[str] | None = None
    verification_summary: str | None = None
    risk_notes: list[str] | None = None


class AgentTeamTaskResponse(BaseModel):
    task: AgentTeamTask


class AgentTeamTaskListResponse(BaseModel):
    tasks: list[AgentTeamTask] = Field(default_factory=list)
    items: list[AgentTeamTask] = Field(default_factory=list)
    count: int = 0


class AgentTeamDispatchResponse(BaseModel):
    session: AgentTeamSession
    tasks: list[AgentTeamTask] = Field(default_factory=list)
    items: list[AgentTeamTask] = Field(default_factory=list)
    count: int = 0


class RecordAgentTeamTaskOutputRequest(BaseModel):
    kind: AgentTeamArtifactKind | None = None
    artifact_kind: AgentTeamArtifactKind | None = None
    artifact_id: str | None = None
    content: str | None = None
    summary: str = ""
    changed_files: list[str] = Field(default_factory=list)
    test_evidence: list[str] = Field(default_factory=list)
    verification_summary: str | None = None
    risk_notes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentTeamTaskOutputResponse(BaseModel):
    output: AgentTeamTaskOutput
    task: AgentTeamTask | None = None


class AgentTeamMergeBundleResponse(BaseModel):
    bundle: AgentTeamMergeBundle


class ApplyAgentTeamMergeDecisionRequest(BaseModel):
    approved: bool = True
    apply: bool | None = None
    action: AgentTeamRecommendedAction | None = None
    next_action: AgentTeamRecommendedAction | None = None
    rationale: str | None = None
    accepted_tasks: list[str] | None = None
    rejected_tasks: list[str] | None = None


class AgentTeamMergeDecisionResponse(BaseModel):
    decision: AgentTeamMergeDecision
    session: AgentTeamSession | None = None
    merge_bundle: AgentTeamMergeBundle | None = None
    applied: bool = False


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


class TrajectoryBatchPromotionPreviewResponse(BaseModel):
    items: list[TrajectoryPromotionResponse] = Field(default_factory=list)
    count: int = 0
    filters: dict[str, Any] = Field(default_factory=dict)
    limit: int
    offset: int
    jsonl: str = ''


class TrajectoryBatchReplaySummaryResponse(BaseModel):
    total: int = 0
    passed: int = 0
    failed: int = 0
    source_failed: int = 0
    tool_path_changed: int = 0


class TrajectoryBatchReplayCompareResponse(BaseModel):
    results: list[TrajectoryReplayResponse] = Field(default_factory=list)
    summary: TrajectoryBatchReplaySummaryResponse = Field(default_factory=TrajectoryBatchReplaySummaryResponse)
    filters: dict[str, Any] = Field(default_factory=dict)
    limit: int
    offset: int


__all__ = [
    "ApplyMergeDecisionRequest",
    "UpdateAgentTeamTaskRequest",
    "RecordAgentTeamTaskOutputRequest",
    "CreateAgentTeamTaskRequest",
    "CreateAgentTeamSessionRequest",
    "DispatchAgentTeamSessionRequest",
    "ApplyAgentTeamMergeDecisionRequest",
    "AgentTeamDispatchResponse",
    "AgentTeamTaskResponse",
    "AgentTeamTaskOutputResponse",
    "AgentTeamTaskListResponse",
    "AgentTeamSessionResponse",
    "AgentTeamSessionListResponse",
    "AgentTeamMergeDecisionResponse",
    "AgentTeamMergeBundleResponse",
    "ApplyMergeDecisionResponse",
    "AgentRoleDecisionListResponse",
    "AgentRoleDryRunRequest",
    "AgentRoleDryRunResponse",
    "AgentRolePolicyResponse",
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
    "TrajectoryBatchFilterRequest",
    "TrajectoryBatchPromotionPreviewRequest",
    "TrajectoryBatchPromotionPreviewResponse",
    "TrajectoryBatchReplayCompareRequest",
    "TrajectoryBatchReplayCompareResponse",
    "TrajectoryBatchReplaySummaryResponse",
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
