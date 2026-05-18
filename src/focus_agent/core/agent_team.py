from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from focus_agent.delegation.roles import AgentRole


class AgentTeamSessionStatus(StrEnum):
    PLANNING = "planning"
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    MERGING = "merging"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentTeamTaskRole(StrEnum):
    PLANNER = "planner"
    ARCHITECT = "architect"
    BACKEND_EXECUTOR = "backend_executor"
    FRONTEND_EXECUTOR = "frontend_executor"
    TEST_ENGINEER = "test_engineer"
    REVIEWER = "reviewer"
    VERIFIER = "verifier"
    WRITER = "writer"


_AGENT_TEAM_TASK_ROLE_TO_AGENT_ROLE: dict[AgentTeamTaskRole, AgentRole] = {
    AgentTeamTaskRole.PLANNER: AgentRole.PLANNER,
    AgentTeamTaskRole.ARCHITECT: AgentRole.ORCHESTRATOR,
    AgentTeamTaskRole.BACKEND_EXECUTOR: AgentRole.EXECUTOR,
    AgentTeamTaskRole.FRONTEND_EXECUTOR: AgentRole.EXECUTOR,
    AgentTeamTaskRole.TEST_ENGINEER: AgentRole.CRITIC,
    AgentTeamTaskRole.REVIEWER: AgentRole.CRITIC,
    AgentTeamTaskRole.VERIFIER: AgentRole.CRITIC,
    AgentTeamTaskRole.WRITER: AgentRole.EXECUTOR,
}


def agent_role_for_team_task_role(role: AgentTeamTaskRole | str) -> AgentRole:
    """Map Workbench task roles to governed execution roles."""
    return _AGENT_TEAM_TASK_ROLE_TO_AGENT_ROLE[AgentTeamTaskRole(role)]


class AgentTeamTaskStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    BLOCKED = "blocked"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentTeamArtifactKind(StrEnum):
    PLAN = "plan"
    PATCH_SUMMARY = "patch_summary"
    TEST_REPORT = "test_report"
    REVIEW_REPORT = "review_report"
    RISK_REPORT = "risk_report"
    HANDOFF = "handoff"
    MERGE_SUMMARY = "merge_summary"


class AgentTeamRecommendedAction(StrEnum):
    MERGE = "merge"
    REQUEST_CHANGES = "request_changes"
    SPLIT_FOLLOWUP = "split_followup"
    DISCARD = "discard"


class AgentTeamFinalAnswerStatus(StrEnum):
    READY = "ready"
    PLACEHOLDER = "placeholder"
    BLOCKED = "blocked"
    ERROR = "error"


class AgentTeamMergeReviewStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    APPROVED = "approved"
    APPLIED = "applied"
    REJECTED = "rejected"
    CONFLICT = "conflict"
    ERROR = "error"


class AgentTeamSession(BaseModel):
    session_id: str
    root_thread_id: str
    user_id: str
    title: str
    goal: str
    status: AgentTeamSessionStatus = AgentTeamSessionStatus.PLANNING
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
    skill_plan: dict[str, Any] = Field(default_factory=dict)


class AgentTeamTask(BaseModel):
    task_id: str
    session_id: str
    branch_id: str | None = None
    child_thread_id: str | None = None
    role: AgentTeamTaskRole
    title: str | None = None
    goal: str
    scope: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
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
    context_refs: list[dict[str, Any]] = Field(default_factory=list)
    active_skill_ids: list[str] = Field(default_factory=list)
    skill_resolution_events: list[dict[str, Any]] = Field(default_factory=list)
    status: AgentTeamTaskStatus = AgentTeamTaskStatus.PENDING
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
    attempt: int = 0
    max_attempts: int = 2
    claim_token: str | None = None
    claim_owner: str | None = None
    claimed_until: str | None = None
    queued_at: str | None = None
    heartbeat_at: str | None = None
    execution_mode: str | None = None
    cancel_requested_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    last_error: str | None = None
    created_at: str
    updated_at: str


class AgentTeamTaskOutput(BaseModel):
    output_id: str
    task_id: str
    kind: AgentTeamArtifactKind = AgentTeamArtifactKind.HANDOFF
    artifact_id: str | None = None
    summary: str = ""
    changed_files: list[str] = Field(default_factory=list)
    test_evidence: list[str] = Field(default_factory=list)
    workspace_id: str | None = None
    workspace_branch: str | None = None
    workspace_path: str | None = None
    base_commit: str | None = None
    diff_summary: str | None = None
    workspace_status: str | None = None
    risk_notes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class AgentTeamMergeBundle(BaseModel):
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


class AgentTeamMergeDecision(BaseModel):
    decision_id: str
    session_id: str
    approved: bool = True
    action: AgentTeamRecommendedAction = AgentTeamRecommendedAction.MERGE
    rationale: str | None = None
    accepted_tasks: list[str] = Field(default_factory=list)
    rejected_tasks: list[str] = Field(default_factory=list)
    created_at: str


class AgentTeamMergeReview(BaseModel):
    review_id: str
    session_id: str
    user_id: str
    status: AgentTeamMergeReviewStatus = AgentTeamMergeReviewStatus.DRAFT
    title: str | None = None
    summary: str | None = None
    selected_task_ids: list[str] = Field(default_factory=list)
    excluded_task_ids: list[str] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    diffstat: str | None = None
    test_evidence: list[str] = Field(default_factory=list)
    risk_items: list[str] = Field(default_factory=list)
    task_summaries: list[dict[str, Any]] = Field(default_factory=list)
    conflict_files: list[str] = Field(default_factory=list)
    error_message: str | None = None
    apply_target_path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str
    previewed_at: str | None = None
    applied_at: str | None = None
    rejected_at: str | None = None


class AgentTeamMergeReviewEvent(BaseModel):
    event_id: str
    review_id: str
    session_id: str
    event_type: str
    status: AgentTeamMergeReviewStatus | None = None
    message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str


__all__ = [
    "AgentTeamArtifactKind",
    "AgentTeamFinalAnswerStatus",
    "AgentTeamMergeBundle",
    "AgentTeamMergeDecision",
    "AgentTeamMergeReview",
    "AgentTeamMergeReviewEvent",
    "AgentTeamMergeReviewStatus",
    "AgentTeamRecommendedAction",
    "AgentTeamSession",
    "AgentTeamSessionStatus",
    "AgentTeamTask",
    "AgentTeamTaskOutput",
    "AgentTeamTaskRole",
    "AgentTeamTaskStatus",
    "agent_role_for_team_task_role",
]
