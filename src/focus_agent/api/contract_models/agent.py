from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


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
    usage_examples: list[str] = Field(default_factory=list)
    negative_examples: list[str] = Field(default_factory=list)
    max_calls_per_turn: int | None = None
    output_summary_contract: str | None = None
    sensitive_args: list[str] = Field(default_factory=list)
    redaction_policy: str = "mask"
    provider_id: str | None = None


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


__all__ = [
    "AgentRolePolicyResponse",
    "AgentRoleDryRunRequest",
    "AgentRoleDryRunResponse",
    "AgentRoleDecisionListResponse",
    "AgentCapabilityResponse",
    "AgentCapabilityListResponse",
    "AgentToolRouteRequest",
    "AgentToolRouteResponse",
    "AgentToolRouteDecisionListResponse",
    "AgentMemoryCuratorPolicyResponse",
    "AgentMemoryCuratorEvaluateRequest",
    "AgentMemoryCuratorEvaluateResponse",
    "AgentMemoryCuratorDecisionListResponse",
    "AgentDelegationPolicyResponse",
    "AgentDelegationPlanRequest",
    "AgentDelegationPlanResponse",
    "AgentDelegationRunListResponse",
    "AgentModelRouterPolicyResponse",
    "AgentModelRouteRequest",
    "AgentModelRouteResponse",
    "AgentModelRouterDecisionListResponse",
    "AgentSelfRepairFailureListResponse",
    "AgentSelfRepairPromotePreviewRequest",
    "AgentSelfRepairPromotePreviewResponse",
    "AgentReviewQueueListResponse",
    "AgentReviewQueueDecisionResponse",
    "AgentContextPolicyResponse",
    "AgentContextPreviewRequest",
    "AgentContextPreviewResponse",
    "AgentContextDecisionListResponse",
    "AgentContextArtifactListResponse",
    "AgentTaskLedgerPolicyResponse",
    "AgentTaskLedgerPlanRequest",
    "AgentTaskLedgerPlanResponse",
    "AgentTaskLedgerRunListResponse",
    "AgentArtifactListResponse",
    "AgentArtifactSynthesisRequest",
    "AgentArtifactSynthesisResponse",
    "AgentCriticVerdictListResponse",
    "AgentCriticEvaluateRequest",
    "AgentCriticEvaluateResponse",
]
