from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from focus_agent.core.agent_team import AgentTeamTaskRole


class AgentTeamPlanOptions(BaseModel):
    replace_existing: bool = False
    granularity: str | None = None
    focus: str | None = None
    max_tasks: int | None = None


class MissionProfile(BaseModel):
    goal: str
    focus: str
    language: str
    risk_level: str = "medium"
    has_backend: bool = False
    has_frontend: bool = False
    requires_code_change: bool = False
    requires_research: bool = False
    requires_verification: bool = False
    requires_review: bool = True
    requires_documentation: bool = False
    write_scope: list[str] = Field(default_factory=list)
    capability_requirements: list[str] = Field(default_factory=list)
    evidence_needs: list[str] = Field(default_factory=list)


class MissionDeliverable(BaseModel):
    key: str
    title: str
    role: AgentTeamTaskRole
    goal: str
    task_type: str
    task_kind: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    scope: list[str] = Field(default_factory=list)
    input_items: list[str] = Field(default_factory=list)
    output_items: list[str] = Field(default_factory=list)
    evidence_required: list[str] = Field(default_factory=list)
    capability_requirements: list[str] = Field(default_factory=list)
    risk_level: str = "medium"
    write_scope: list[str] = Field(default_factory=list)
    resource_claims: list[str] = Field(default_factory=list)
    replan_when: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    planning_rationale: str


class AgentTeamTaskDraft(BaseModel):
    key: str
    title: str
    role: AgentTeamTaskRole
    goal: str
    scope: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    context_refs: list[dict[str, Any]] = Field(default_factory=list)
    planning_rationale: str
    sort_order: int
    task_type: str = "execution"
    task_kind: str | None = None
    input_contract: dict[str, Any] | None = None
    output_contract: dict[str, Any] | None = None
    evidence_required: list[str] = Field(default_factory=list)
    capability_requirements: list[str] = Field(default_factory=list)
    risk_level: str | None = None
    write_scope: list[str] = Field(default_factory=list)
    resource_claims: list[str] = Field(default_factory=list)
    replan_policy: dict[str, Any] | None = None
    plan_source: str
    active_skill_ids: list[str] = Field(default_factory=list)
    skill_resolution_events: list[dict[str, Any]] = Field(default_factory=list)


class AgentTeamPlanDraft(BaseModel):
    planning_source: str
    planning_rationale: str
    planner_model_id: str | None = None
    planning_error: str | None = None
    plan_hash: str
    skill_plan: dict[str, Any] = Field(default_factory=dict)
    tasks: list[AgentTeamTaskDraft] = Field(default_factory=list)


__all__ = [
    "AgentTeamPlanDraft",
    "AgentTeamPlanOptions",
    "AgentTeamTaskDraft",
    "MissionDeliverable",
    "MissionProfile",
]
