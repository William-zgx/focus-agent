from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from focus_agent.core.agent_team import (
    AgentTeamArtifactKind,
    AgentTeamMergeDecision,
    AgentTeamMergeReview,
    AgentTeamMergeReviewEvent,
    AgentTeamMergeReviewStatus,
    AgentTeamRecommendedAction,
    AgentTeamSessionStatus,
    AgentTeamTaskOutput,
    AgentTeamTaskRole,
    AgentTeamTaskStatus,
)

AgentTeamPlanGranularity = Literal["auto", "coarse", "balanced", "detailed"]
AgentTeamPlanFocus = Literal[
    "auto",
    "research",
    "debugging",
    "review",
    "implementation",
    "verification",
    "writing",
]
AgentTeamFinalAnswerStatus = Literal["ready", "placeholder", "blocked", "error"] | str


class AgentTeamPlanningMetadata(BaseModel):
    source: str | None = None
    rationale: str | None = None
    planner_model_id: str | None = None
    generated_at: str | None = None
    plan_hash: str | None = None
    error: str | None = None
    task_count: int = 0


class AgentTeamRunMetadata(BaseModel):
    execution_mode: str | None = None
    scheduled_task_ids: list[str] = Field(default_factory=list)
    running_task_ids: list[str] = Field(default_factory=list)
    max_parallel_runs: int = 1


class AgentTeamSchedulerMetadata(BaseModel):
    ready_task_ids: list[str] = Field(default_factory=list)
    waiting_task_ids: list[str] = Field(default_factory=list)
    blocked_task_ids: list[str] = Field(default_factory=list)
    max_waves: int = 0
    max_tasks: int = 0


class AgentTeamToolApprovalContract(BaseModel):
    request_id: str
    session_id: str
    agent_id: str
    tool_name: str
    tool_args: dict[str, Any] = Field(default_factory=dict)
    risk_level: str = "low"
    status: str = "pending"
    submitted_at: float = 0.0
    timeout_at: float = 0.0
    decided_by: str | None = None


class AgentTeamSessionContract(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: str
    root_thread_id: str
    user_id: str
    title: str
    goal: str
    status: AgentTeamSessionStatus
    created_at: str
    updated_at: str
    latest_merge_bundle: dict[str, Any] | None = None
    merge_decision: dict[str, Any] | None = None
    planning_source: str | None = None
    planning_rationale: str | None = None
    planner_model_id: str | None = None
    plan_generated_at: str | None = None
    plan_hash: str | None = None
    planning_error: str | None = None
    planning: AgentTeamPlanningMetadata | None = None
    skill_plan: dict[str, Any] = Field(default_factory=dict)


class AgentTeamTaskContract(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_id: str
    session_id: str
    branch_id: str | None = None
    child_thread_id: str | None = None
    role: AgentTeamTaskRole
    goal: str
    title: str | None = None
    planning_rationale: str | None = None
    sort_order: int | None = None
    task_type: str | None = None
    task_kind: str | None = None
    plan_source: str | None = None
    input_contract: dict[str, Any] | None = None
    output_contract: dict[str, Any] | None = None
    evidence_required: list[str] = Field(default_factory=list)
    capability_requirements: list[str] = Field(default_factory=list)
    risk_level: str | None = None
    write_scope: list[str] = Field(default_factory=list)
    resource_claims: list[str] = Field(default_factory=list)
    replan_policy: dict[str, Any] | None = None
    scope: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    context_refs: list[dict[str, Any]] = Field(default_factory=list)
    active_skill_ids: list[str] = Field(default_factory=list)
    skill_resolution_events: list[dict[str, Any]] = Field(default_factory=list)
    status: AgentTeamTaskStatus
    run_status: str | None = None
    output_artifact_ids: list[str] = Field(default_factory=list)
    agent_run_id: str | None = None
    delegated_task_id: str | None = None
    artifact_ids: list[str] = Field(default_factory=list)
    execution_status: str | None = None
    workspace_id: str | None = None
    workspace_branch: str | None = None
    workspace_path: str | None = None
    base_commit: str | None = None
    diff_summary: str | None = None
    test_evidence: list[str] = Field(default_factory=list)
    workspace_status: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    verification_summary: str | None = None
    risk_notes: list[str] = Field(default_factory=list)
    started_at: str | None = None
    finished_at: str | None = None
    last_error: str | None = None
    attempt: int = 0
    max_attempts: int = 2
    claim_owner: str | None = None
    claimed_until: str | None = None
    queued_at: str | None = None
    heartbeat_at: str | None = None
    execution_mode: str | None = None
    cancel_requested_at: str | None = None
    created_at: str
    updated_at: str


class AgentTeamMergeBundleContract(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: str
    summary: str
    final_answer: str | None = None
    final_answer_status: AgentTeamFinalAnswerStatus | None = None
    final_answer_warnings: list[str] = Field(default_factory=list)
    source_output_ids: list[str] = Field(default_factory=list)
    accepted_tasks: list[str] = Field(default_factory=list)
    rejected_tasks: list[str] = Field(default_factory=list)
    key_findings: list[str] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    test_evidence: list[str] = Field(default_factory=list)
    execution_evidence: list[dict[str, Any]] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    risk_items: list[str] = Field(default_factory=list)
    recommended_next_action: AgentTeamRecommendedAction = AgentTeamRecommendedAction.REQUEST_CHANGES


class CreateAgentTeamSessionRequest(BaseModel):
    root_thread_id: str | None = None
    title: str | None = None
    goal: str


class AgentTeamSessionResponse(BaseModel):
    session: AgentTeamSessionContract


class AgentTeamSessionListResponse(BaseModel):
    sessions: list[AgentTeamSessionContract] = Field(default_factory=list)
    items: list[AgentTeamSessionContract] = Field(default_factory=list)
    count: int = 0


class CreateAgentTeamTaskRequest(BaseModel):
    role: AgentTeamTaskRole
    goal: str
    task_kind: str | None = None
    input_contract: dict[str, Any] | None = None
    output_contract: dict[str, Any] | None = None
    evidence_required: list[str] = Field(default_factory=list)
    capability_requirements: list[str] = Field(default_factory=list)
    risk_level: str | None = None
    write_scope: list[str] = Field(default_factory=list)
    resource_claims: list[str] = Field(default_factory=list)
    replan_policy: dict[str, Any] | None = None
    scope: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    context_refs: list[dict[str, Any]] = Field(default_factory=list)
    active_skill_ids: list[str] = Field(default_factory=list)
    skill_resolution_events: list[dict[str, Any]] = Field(default_factory=list)
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


class AgentTeamPlanSessionRequest(DispatchAgentTeamSessionRequest):
    replace_existing: bool | None = None
    granularity: AgentTeamPlanGranularity | None = None
    focus: AgentTeamPlanFocus | None = None
    max_tasks: int | None = Field(default=None, ge=1)


class RunAgentTeamSessionRequest(BaseModel):
    task_ids: list[str] = Field(default_factory=list)
    run_ready_only: bool | None = None
    metadata: dict[str, Any] | None = None
    create_branches: bool | None = None
    auto_fork_branch: bool | None = None
    parent_thread_id: str | None = None


class UpdateAgentTeamTaskRequest(BaseModel):
    status: AgentTeamTaskStatus | None = None
    goal: str | None = None
    scope: list[str] | None = None
    dependencies: list[str] | None = None
    acceptance_criteria: list[str] | None = None
    context_refs: list[dict[str, Any]] | None = None
    active_skill_ids: list[str] | None = None
    skill_resolution_events: list[dict[str, Any]] | None = None
    input_contract: dict[str, Any] | None = None
    output_contract: dict[str, Any] | None = None
    evidence_required: list[str] | None = None
    capability_requirements: list[str] | None = None
    risk_level: str | None = None
    write_scope: list[str] | None = None
    resource_claims: list[str] | None = None
    replan_policy: dict[str, Any] | None = None
    branch_id: str | None = None
    child_thread_id: str | None = None
    output_artifact_ids: list[str] | None = None
    changed_files: list[str] | None = None
    test_evidence: list[str] | None = None
    verification_summary: str | None = None
    risk_notes: list[str] | None = None
    workspace_id: str | None = None
    workspace_branch: str | None = None
    workspace_path: str | None = None
    base_commit: str | None = None
    diff_summary: str | None = None
    workspace_status: str | None = None
    run_status: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    last_error: str | None = None


class AgentTeamTaskResponse(BaseModel):
    task: AgentTeamTaskContract


class AgentTeamTaskListResponse(BaseModel):
    tasks: list[AgentTeamTaskContract] = Field(default_factory=list)
    items: list[AgentTeamTaskContract] = Field(default_factory=list)
    count: int = 0


class AgentTeamDispatchResponse(BaseModel):
    session: AgentTeamSessionContract
    tasks: list[AgentTeamTaskContract] = Field(default_factory=list)
    items: list[AgentTeamTaskContract] = Field(default_factory=list)
    count: int = 0
    planning: AgentTeamPlanningMetadata | None = None


class AgentTeamSessionViewResponse(BaseModel):
    session: AgentTeamSessionContract
    tasks: list[AgentTeamTaskContract] = Field(default_factory=list)
    items: list[AgentTeamTaskContract] = Field(default_factory=list)
    count: int = 0
    outputs: list[AgentTeamTaskOutput] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    merge_bundle: AgentTeamMergeBundleContract | None = None
    planning: AgentTeamPlanningMetadata | None = None
    run: AgentTeamRunMetadata | None = None
    scheduler: AgentTeamSchedulerMetadata | None = None
    pending_tool_approvals: list[AgentTeamToolApprovalContract] = Field(default_factory=list)


class AgentTeamToolApprovalListResponse(BaseModel):
    approvals: list[AgentTeamToolApprovalContract] = Field(default_factory=list)
    items: list[AgentTeamToolApprovalContract] = Field(default_factory=list)
    count: int = 0


class DecideAgentTeamToolApprovalRequest(BaseModel):
    approved: bool
    reason: str | None = None


class AgentTeamToolApprovalActionRequest(BaseModel):
    reason: str | None = None


class AgentTeamToolApprovalDecisionResponse(BaseModel):
    approval: AgentTeamToolApprovalContract


class RecordAgentTeamTaskOutputRequest(BaseModel):
    kind: AgentTeamArtifactKind | None = None
    artifact_kind: AgentTeamArtifactKind | None = None
    artifact_id: str | None = None
    content: str | None = None
    summary: str = ""
    changed_files: list[str] = Field(default_factory=list)
    test_evidence: list[str] = Field(default_factory=list)
    verification_summary: str | None = None
    workspace_id: str | None = None
    workspace_branch: str | None = None
    workspace_path: str | None = None
    base_commit: str | None = None
    diff_summary: str | None = None
    workspace_status: str | None = None
    risk_notes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentTeamTaskOutputResponse(BaseModel):
    output: AgentTeamTaskOutput
    task: AgentTeamTaskContract | None = None


class AgentTeamMergeBundleResponse(BaseModel):
    bundle: AgentTeamMergeBundleContract


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
    session: AgentTeamSessionContract | None = None
    merge_bundle: AgentTeamMergeBundleContract | None = None
    applied: bool = False


class CreateAgentTeamMergeReviewRequest(BaseModel):
    selected_task_ids: list[str] | None = None
    excluded_task_ids: list[str] | None = None
    title: str | None = None
    metadata: dict[str, Any] | None = None


class UpdateAgentTeamMergeReviewRequest(BaseModel):
    selected_task_ids: list[str] | None = None
    excluded_task_ids: list[str] | None = None
    status: AgentTeamMergeReviewStatus | None = None
    title: str | None = None
    metadata: dict[str, Any] | None = None


class ApplyAgentTeamMergeReviewRequest(BaseModel):
    apply_target_path: str | None = None


class RejectAgentTeamMergeReviewRequest(BaseModel):
    rationale: str | None = None


class AgentTeamMergeReviewResponse(BaseModel):
    review: AgentTeamMergeReview
    events: list[AgentTeamMergeReviewEvent] = Field(default_factory=list)


class AgentTeamMergeReviewListResponse(BaseModel):
    reviews: list[AgentTeamMergeReview] = Field(default_factory=list)
    items: list[AgentTeamMergeReview] = Field(default_factory=list)
    count: int = 0
    latest: AgentTeamMergeReview | None = None


class AgentTeamMergeReviewCaptureResponse(BaseModel):
    capture: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "CreateAgentTeamSessionRequest",
    "AgentTeamPlanGranularity",
    "AgentTeamPlanFocus",
    "AgentTeamPlanningMetadata",
    "AgentTeamRunMetadata",
    "AgentTeamToolApprovalContract",
    "RunAgentTeamSessionRequest",
    "AgentTeamFinalAnswerStatus",
    "AgentTeamSessionContract",
    "AgentTeamTaskContract",
    "AgentTeamMergeBundleContract",
    "AgentTeamSessionResponse",
    "AgentTeamSessionListResponse",
    "CreateAgentTeamTaskRequest",
    "DispatchAgentTeamSessionRequest",
    "AgentTeamPlanSessionRequest",
    "UpdateAgentTeamTaskRequest",
    "AgentTeamTaskResponse",
    "AgentTeamTaskListResponse",
    "AgentTeamDispatchResponse",
    "AgentTeamSessionViewResponse",
    "AgentTeamToolApprovalListResponse",
    "DecideAgentTeamToolApprovalRequest",
    "AgentTeamToolApprovalActionRequest",
    "AgentTeamToolApprovalDecisionResponse",
    "RecordAgentTeamTaskOutputRequest",
    "AgentTeamTaskOutputResponse",
    "AgentTeamMergeBundleResponse",
    "ApplyAgentTeamMergeDecisionRequest",
    "AgentTeamMergeDecisionResponse",
    "CreateAgentTeamMergeReviewRequest",
    "UpdateAgentTeamMergeReviewRequest",
    "ApplyAgentTeamMergeReviewRequest",
    "RejectAgentTeamMergeReviewRequest",
    "AgentTeamMergeReviewResponse",
    "AgentTeamMergeReviewListResponse",
    "AgentTeamMergeReviewCaptureResponse",
]
