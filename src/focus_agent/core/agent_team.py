from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from focus_agent.agent_roles import AgentRole


class AgentTeamSessionStatus(str, Enum):
    PLANNING = "planning"
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    MERGING = "merging"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentTeamTaskRole(str, Enum):
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


class AgentTeamTaskStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    BLOCKED = "blocked"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentTeamArtifactKind(str, Enum):
    PLAN = "plan"
    PATCH_SUMMARY = "patch_summary"
    TEST_REPORT = "test_report"
    REVIEW_REPORT = "review_report"
    RISK_REPORT = "risk_report"
    HANDOFF = "handoff"
    MERGE_SUMMARY = "merge_summary"


class AgentTeamRecommendedAction(str, Enum):
    MERGE = "merge"
    REQUEST_CHANGES = "request_changes"
    SPLIT_FOLLOWUP = "split_followup"
    DISCARD = "discard"


class AgentTeamFinalAnswerStatus(str, Enum):
    READY = "ready"
    PLACEHOLDER = "placeholder"
    BLOCKED = "blocked"
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
    plan_source: str | None = None
    context_refs: list[dict[str, Any]] = Field(default_factory=list)
    status: AgentTeamTaskStatus = AgentTeamTaskStatus.PENDING
    run_status: str | None = None
    output_artifact_ids: list[str] = Field(default_factory=list)
    agent_run_id: str | None = None
    delegated_task_id: str | None = None
    artifact_ids: list[str] = Field(default_factory=list)
    execution_status: str | None = None
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


__all__ = [
    "AgentTeamArtifactKind",
    "AgentTeamFinalAnswerStatus",
    "AgentTeamMergeBundle",
    "AgentTeamMergeDecision",
    "AgentTeamRecommendedAction",
    "AgentTeamSession",
    "AgentTeamSessionStatus",
    "AgentTeamTask",
    "AgentTeamTaskOutput",
    "AgentTeamTaskRole",
    "AgentTeamTaskStatus",
    "agent_role_for_team_task_role",
]
