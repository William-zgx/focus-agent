from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


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


class AgentTeamTaskStatus(str, Enum):
    PENDING = "pending"
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


class AgentTeamTask(BaseModel):
    task_id: str
    session_id: str
    branch_id: str | None = None
    child_thread_id: str | None = None
    role: AgentTeamTaskRole
    goal: str
    scope: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    status: AgentTeamTaskStatus = AgentTeamTaskStatus.PENDING
    output_artifact_ids: list[str] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    verification_summary: str | None = None
    risk_notes: list[str] = Field(default_factory=list)
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
    accepted_tasks: list[str] = Field(default_factory=list)
    rejected_tasks: list[str] = Field(default_factory=list)
    key_findings: list[str] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    test_evidence: list[str] = Field(default_factory=list)
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
    "AgentTeamMergeBundle",
    "AgentTeamMergeDecision",
    "AgentTeamRecommendedAction",
    "AgentTeamSession",
    "AgentTeamSessionStatus",
    "AgentTeamTask",
    "AgentTeamTaskOutput",
    "AgentTeamTaskRole",
    "AgentTeamTaskStatus",
]
