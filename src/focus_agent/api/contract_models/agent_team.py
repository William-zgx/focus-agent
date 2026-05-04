from __future__ import annotations

from typing import Any

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


__all__ = [
    "CreateAgentTeamSessionRequest",
    "AgentTeamSessionResponse",
    "AgentTeamSessionListResponse",
    "CreateAgentTeamTaskRequest",
    "DispatchAgentTeamSessionRequest",
    "UpdateAgentTeamTaskRequest",
    "AgentTeamTaskResponse",
    "AgentTeamTaskListResponse",
    "AgentTeamDispatchResponse",
    "RecordAgentTeamTaskOutputRequest",
    "AgentTeamTaskOutputResponse",
    "AgentTeamMergeBundleResponse",
    "ApplyAgentTeamMergeDecisionRequest",
    "AgentTeamMergeDecisionResponse",
]
