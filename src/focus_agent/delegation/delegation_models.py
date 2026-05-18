from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .execution_modes import DelegationExecutionMode
from .roles import AgentRole
from ..core.types import StateModel

AgentRunStatus = Literal["planned", "running", "completed", "failed", "skipped", "needs_review"]
AgentDecisionKind = Literal["route", "delegate", "retry", "deny", "approve", "reject"]
AgentFailureType = Literal[
    "planning_gap",
    "tool_denied",
    "forbidden_tool_attempt",
    "memory_scope_violation",
    "critic_rejected",
    "model_protocol_error",
    "budget_exceeded",
]
ReviewItemStatus = Literal["pending", "approved", "rejected"]


class AgentBudget(StateModel):
    max_llm_calls: int = Field(default=1, ge=0)
    max_tool_calls: int = Field(default=3, ge=0)
    max_cost_usd: float = Field(default=0.0, ge=0.0)


class AgentTask(StateModel):
    task_id: str
    parent_task_id: str | None = None
    role: AgentRole
    goal: str
    constraints: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    memory_scope: str = "thread"
    budget: AgentBudget = Field(default_factory=AgentBudget)
    acceptance_criteria: list[str] = Field(default_factory=list)
    max_turns: int = Field(default=1, ge=0)
    timeout_seconds: int = Field(default=30, ge=0)
    max_depth: int = Field(default=1, ge=-1)
    requires_workspace_write: bool = False
    requires_network: bool = False
    context_refs: list[dict[str, Any]] = Field(default_factory=list)
    run_isolation_key: str = ""
    workspace_id: str | None = None
    workspace_path: str | None = None
    workspace_branch: str | None = None
    base_commit: str | None = None


class AgentArtifact(StateModel):
    artifact_id: str
    kind: str = "evidence"
    title: str
    summary: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentRun(StateModel):
    run_id: str
    task_id: str
    role: AgentRole
    status: AgentRunStatus = "planned"
    model_id: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    tool_calls: int = 0
    cost: float = 0.0
    artifacts: list[AgentArtifact] = Field(default_factory=list)
    error: str | None = None
    execution_mode: DelegationExecutionMode = "observe"


class AgentDecision(StateModel):
    decision_id: str
    kind: AgentDecisionKind
    role: AgentRole
    task_id: str | None = None
    rationale: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentDelegationPlan(StateModel):
    enabled: bool = False
    enforce: bool = False
    execution_mode: DelegationExecutionMode = "observe"
    source: str = "disabled"
    route_reason: str = ""
    max_parallel_runs: int = 1
    tasks: list[AgentTask] = Field(default_factory=list)
    runs: list[AgentRun] = Field(default_factory=list)
    decisions: list[AgentDecision] = Field(default_factory=list)
    legacy_execution_unchanged: bool = True
    skipped_reason: str = ""


class ModelRouteDecision(StateModel):
    enabled: bool = False
    mode: Literal["observe", "enforce"] = "observe"
    role: AgentRole = AgentRole.EXECUTOR
    selected_model: str
    recommended_model: str
    effective_model: str
    route_reason: str = ""
    fallback_used: bool = False
    candidates: list[str] = Field(default_factory=list)


class AgentFailureRecord(StateModel):
    failure_id: str
    failure_type: AgentFailureType
    failed_role: AgentRole
    failed_task_id: str | None = None
    tool_route_plan: dict[str, Any] = Field(default_factory=dict)
    memory_scope: str = "thread"
    model_id: str | None = None
    trajectory_id: str | None = None
    message: str = ""


class AgentReviewItem(StateModel):
    item_id: str
    item_type: str
    status: ReviewItemStatus = "pending"
    role: AgentRole | None = None
    task_id: str | None = None
    summary: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentSelfRepairPreview(StateModel):
    enabled: bool = False
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    failures: list[AgentFailureRecord] = Field(default_factory=list)


__all__ = [
    "AgentArtifact",
    "AgentBudget",
    "AgentDecision",
    "AgentDecisionKind",
    "AgentDelegationPlan",
    "AgentFailureRecord",
    "AgentFailureType",
    "AgentReviewItem",
    "AgentRun",
    "AgentRunStatus",
    "AgentSelfRepairPreview",
    "AgentTask",
    "DelegationExecutionMode",
    "ModelRouteDecision",
    "ReviewItemStatus",
]
