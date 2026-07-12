from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from focus_agent.core.users import UserStatus
from focus_agent.engine.runtime import AppRuntime
from focus_agent.security.permissions import is_admin_role, permissions_for_roles
from focus_agent.security.tokens import Principal

from ..contracts import (
    AgentArtifactListResponse,
    AgentArtifactSynthesisRequest,
    AgentArtifactSynthesisResponse,
    AgentCapabilityListResponse,
    AgentContextArtifactListResponse,
    AgentContextDecisionListResponse,
    AgentContextEvidenceListResponse,
    AgentContextExplainRequest,
    AgentContextExplainResponse,
    AgentContextPolicyResponse,
    AgentContextPreviewRequest,
    AgentContextPreviewResponse,
    AgentCriticEvaluateRequest,
    AgentCriticEvaluateResponse,
    AgentCriticVerdictListResponse,
    AgentDelegationPlanRequest,
    AgentDelegationPlanResponse,
    AgentDelegationPolicyResponse,
    AgentDelegationRunListResponse,
    AgentFeedbackTrendResponse,
    AgentMemoryCuratorDecisionListResponse,
    AgentMemoryCuratorEvaluateRequest,
    AgentMemoryCuratorEvaluateResponse,
    AgentMemoryCuratorPolicyResponse,
    AgentModelRouterDecisionListResponse,
    AgentModelRouteRequest,
    AgentModelRouteResponse,
    AgentModelRouterPolicyResponse,
    AgentReviewQueueDecisionResponse,
    AgentReviewQueueListResponse,
    AgentRoleDecisionListResponse,
    AgentRoleDryRunRequest,
    AgentRoleDryRunResponse,
    AgentRolePolicyResponse,
    AgentSelfRepairFailureListResponse,
    AgentSelfRepairPromotePreviewRequest,
    AgentSelfRepairPromotePreviewResponse,
    AgentSkillCatalogResponse,
    AgentSkillPreferenceRequest,
    AgentSkillPreferenceResponse,
    AgentSkillSelectionEventListResponse,
    AgentSkillSelectionFeedbackRequest,
    AgentSkillSelectionFeedbackResponse,
    AgentSkillSelectionResponse,
    AgentSkillSelectRequest,
    AgentSkillSemanticCandidateResponse,
    AgentTaskLedgerPlanRequest,
    AgentTaskLedgerPlanResponse,
    AgentTaskLedgerPolicyResponse,
    AgentTaskLedgerRunListResponse,
    AgentToolRouteDecisionListResponse,
    AgentToolRouteRequest,
    AgentToolRouteResponse,
    AgentToolsetListResponse,
)
from ..deps import get_app_runtime, get_current_principal
from ..route_utils.agent_governance import (
    _agent_artifact_synthesis_response_with_runtime,
    _agent_artifacts_response,
    _agent_capabilities_response,
    _agent_context_artifacts_response,
    _agent_context_decisions_response,
    _agent_context_policy_response,
    _agent_context_preview_response,
    _agent_critic_evaluate_response,
    _agent_critic_verdicts_response,
    _agent_delegation_plan_response,
    _agent_delegation_policy_response,
    _agent_delegation_runs_response,
    _agent_memory_curator_decisions_response,
    _agent_memory_curator_evaluate_response,
    _agent_memory_curator_policy_response,
    _agent_model_route_response,
    _agent_model_router_decisions_response,
    _agent_model_router_policy_response,
    _agent_review_queue_decision_response,
    _agent_review_queue_response,
    _agent_role_decisions_response,
    _agent_role_dry_run_response,
    _agent_role_policy_response,
    _agent_self_repair_failures_response,
    _agent_self_repair_preview_response,
    _agent_task_ledger_plan_response,
    _agent_task_ledger_policy_response,
    _agent_task_ledger_runs_response,
    _agent_tool_route_decisions_response,
    _agent_tool_route_response,
    _agent_toolsets_response,
)
from ..route_utils.agent_governance_operations import (
    _agent_context_evidence_list_response,
    _agent_context_explain_response,
    _agent_feedback_trend_response,
    _agent_skill_catalog_response,
    _agent_skill_preference_response,
    _agent_skill_selection_events_response,
    _agent_skill_selection_feedback_response,
    _persist_skill_selection_event,
)
from ..route_utils.agent_governance_trajectory_responses import _scoped_governance_runtime

router = APIRouter()
_GLOBAL_GOVERNANCE_PERMISSIONS = {
    "governance:read:global",
    "governance:trajectories:read:global",
}


def _governance_list_runtime(
    *,
    runtime: AppRuntime,
    principal: Principal,
) -> AppRuntime:
    return _scoped_governance_runtime(
        runtime,
        owner_user_id=(
            None
            if _can_view_global_governance(runtime=runtime, principal=principal)
            else principal.user_id
        ),
        thread_id=None,
    )


def _can_view_global_governance(*, runtime: AppRuntime, principal: Principal) -> bool:
    if not bool(getattr(runtime.settings, "auth_enabled", False)):
        return False

    user_service = getattr(runtime, "user_service", None)
    if user_service is None:
        return False
    try:
        user = user_service.get_user(principal.user_id)
    except Exception:  # noqa: BLE001
        return False
    if str(getattr(user.status, "value", user.status)) != UserStatus.ACTIVE.value:
        return False
    claim_permissions = _claim_values(principal.claims.get("permissions"))
    claim_permissions.update(_claim_values(principal.claims.get("permission")))
    granted = set(principal.scopes)
    granted.update(claim_permissions)
    return is_admin_role(user.roles) or bool(
        _GLOBAL_GOVERNANCE_PERMISSIONS.intersection(
            granted.union(permissions_for_roles(user.roles))
        )
    )


def _claim_values(raw: object) -> set[str]:
    if raw is None:
        return set()
    if isinstance(raw, str):
        return {item for item in raw.replace(",", " ").split() if item}
    if isinstance(raw, (list, tuple, set, frozenset)):
        return {str(item).strip() for item in raw if str(item).strip()}
    value = str(raw).strip()
    return {value} if value else set()


def _skill_selection_response(
    *,
    payload: AgentSkillSelectRequest,
    runtime: AppRuntime,
) -> AgentSkillSelectionResponse:
    registry = runtime.skill_registry
    threshold = (
        float(payload.semantic_threshold)
        if payload.semantic_threshold is not None
        else float(getattr(runtime.settings, "skill_semantic_match_threshold", 0.22))
    )
    semantic_enabled = (
        bool(payload.semantic_enabled)
        if payload.semantic_enabled is not None
        else bool(getattr(runtime.settings, "skill_semantic_match_enabled", True))
    )
    selection = registry.select_for_message(
        payload.message,
        explicit_hints=payload.skill_hints,
        semantic_match_enabled=semantic_enabled,
        semantic_match_threshold=threshold,
    )
    return AgentSkillSelectionResponse(
        skill_ids=list(selection.skill_ids),
        stripped_message=selection.stripped_message,
        prompt_mode=selection.prompt_mode.value if selection.prompt_mode else None,
        selection_source=selection.selection_source,
        matched_triggers=list(selection.matched_triggers),
        semantic_candidates=[
            AgentSkillSemanticCandidateResponse(
                skill_id=candidate.skill_id,
                score=candidate.score,
                matched_terms=list(candidate.matched_terms),
                auto_activate=candidate.auto_activate,
                rationale=candidate.rationale,
            )
            for candidate in selection.semantic_candidates
        ],
        confidence=selection.confidence,
        rationale=selection.rationale,
        semantic_enabled=semantic_enabled,
        semantic_threshold=threshold,
    )


@router.get("/v1/agent/roles/policy", response_model=AgentRolePolicyResponse)
def get_agent_role_policy(
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentRolePolicyResponse:
    del principal
    return _agent_role_policy_response(runtime.settings)


@router.post("/v1/agent/skills/select", response_model=AgentSkillSelectionResponse)
def select_agent_skills(
    payload: AgentSkillSelectRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentSkillSelectionResponse:
    response = _skill_selection_response(payload=payload, runtime=runtime)
    return _persist_skill_selection_event(
        runtime=runtime,
        principal=principal,
        payload=payload,
        response=response,
    )


@router.get("/v1/agent/skills/selections", response_model=AgentSkillSelectionEventListResponse)
def list_agent_skill_selections(
    skill_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentSkillSelectionEventListResponse:
    return _agent_skill_selection_events_response(
        runtime=runtime,
        principal=principal,
        skill_id=skill_id,
        limit=limit,
    )


@router.post(
    "/v1/agent/skills/selections/{selection_id}/feedback",
    response_model=AgentSkillSelectionFeedbackResponse,
)
def record_agent_skill_selection_feedback(
    selection_id: str,
    payload: AgentSkillSelectionFeedbackRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentSkillSelectionFeedbackResponse:
    return _agent_skill_selection_feedback_response(
        runtime=runtime,
        principal=principal,
        selection_id=selection_id,
        payload=payload,
    )


@router.get("/v1/agent/feedback/trend", response_model=AgentFeedbackTrendResponse)
def get_agent_feedback_trend(
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentFeedbackTrendResponse:
    scoped_runtime = _governance_list_runtime(
        runtime=runtime,
        principal=principal,
    )
    return _agent_feedback_trend_response(runtime=scoped_runtime, principal=principal)


@router.get("/v1/agent/skills/catalog", response_model=AgentSkillCatalogResponse)
def list_agent_skill_catalog(
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentSkillCatalogResponse:
    return _agent_skill_catalog_response(runtime=runtime, principal=principal)


@router.patch("/v1/agent/skills/{skill_id}/preference", response_model=AgentSkillPreferenceResponse)
def update_agent_skill_preference(
    skill_id: str,
    payload: AgentSkillPreferenceRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentSkillPreferenceResponse:
    return _agent_skill_preference_response(
        runtime=runtime,
        principal=principal,
        skill_id=skill_id,
        payload=payload,
    )


@router.post("/v1/agent/roles/dry-run", response_model=AgentRoleDryRunResponse)
def dry_run_agent_role_route(
    payload: AgentRoleDryRunRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentRoleDryRunResponse:
    del principal
    return _agent_role_dry_run_response(payload=payload, runtime=runtime)


@router.get("/v1/agent/roles/decisions", response_model=AgentRoleDecisionListResponse)
def list_agent_role_decisions(
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentRoleDecisionListResponse:
    scoped_runtime = _governance_list_runtime(
        runtime=runtime,
        principal=principal,
    )
    return _agent_role_decisions_response(runtime=scoped_runtime, limit=limit)


@router.get("/v1/agent/capabilities", response_model=AgentCapabilityListResponse)
def list_agent_capabilities(
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentCapabilityListResponse:
    del principal
    return _agent_capabilities_response(runtime)


@router.get("/v1/agent/toolsets", response_model=AgentToolsetListResponse)
def list_agent_toolsets(
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentToolsetListResponse:
    del principal
    return _agent_toolsets_response(runtime)


@router.post("/v1/agent/tool-router/route", response_model=AgentToolRouteResponse)
def route_agent_tools(
    payload: AgentToolRouteRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentToolRouteResponse:
    del principal
    return _agent_tool_route_response(payload=payload, runtime=runtime)


@router.get("/v1/agent/tool-router/decisions", response_model=AgentToolRouteDecisionListResponse)
def list_agent_tool_route_decisions(
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentToolRouteDecisionListResponse:
    scoped_runtime = _governance_list_runtime(
        runtime=runtime,
        principal=principal,
    )
    return _agent_tool_route_decisions_response(runtime=scoped_runtime, limit=limit)


@router.get("/v1/agent/memory/curator/policy", response_model=AgentMemoryCuratorPolicyResponse)
def get_agent_memory_curator_policy(
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentMemoryCuratorPolicyResponse:
    del principal
    return _agent_memory_curator_policy_response(runtime.settings)


@router.post("/v1/agent/memory/curator/evaluate", response_model=AgentMemoryCuratorEvaluateResponse)
def evaluate_agent_memory_curator(
    payload: AgentMemoryCuratorEvaluateRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentMemoryCuratorEvaluateResponse:
    return _agent_memory_curator_evaluate_response(
        payload=payload,
        runtime=runtime,
        principal_user_id=principal.user_id,
    )


@router.get(
    "/v1/agent/memory/curator/decisions", response_model=AgentMemoryCuratorDecisionListResponse
)
def list_agent_memory_curator_decisions(
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentMemoryCuratorDecisionListResponse:
    scoped_runtime = _governance_list_runtime(
        runtime=runtime,
        principal=principal,
    )
    return _agent_memory_curator_decisions_response(runtime=scoped_runtime, limit=limit)


@router.get("/v1/agent/delegation/policy", response_model=AgentDelegationPolicyResponse)
def get_agent_delegation_policy(
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentDelegationPolicyResponse:
    del principal
    return _agent_delegation_policy_response(runtime.settings)


@router.post("/v1/agent/delegation/plan", response_model=AgentDelegationPlanResponse)
def plan_agent_delegation(
    payload: AgentDelegationPlanRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentDelegationPlanResponse:
    del principal
    return _agent_delegation_plan_response(payload=payload, runtime=runtime)


@router.get("/v1/agent/delegation/runs", response_model=AgentDelegationRunListResponse)
def list_agent_delegation_runs(
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentDelegationRunListResponse:
    scoped_runtime = _governance_list_runtime(
        runtime=runtime,
        principal=principal,
    )
    return _agent_delegation_runs_response(runtime=scoped_runtime, limit=limit)


@router.get("/v1/agent/model-router/policy", response_model=AgentModelRouterPolicyResponse)
def get_agent_model_router_policy(
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentModelRouterPolicyResponse:
    del principal
    return _agent_model_router_policy_response(runtime.settings)


@router.post("/v1/agent/model-router/route", response_model=AgentModelRouteResponse)
def route_agent_model(
    payload: AgentModelRouteRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentModelRouteResponse:
    del principal
    return _agent_model_route_response(payload=payload, runtime=runtime)


@router.get("/v1/agent/model-router/decisions", response_model=AgentModelRouterDecisionListResponse)
def list_agent_model_router_decisions(
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentModelRouterDecisionListResponse:
    scoped_runtime = _governance_list_runtime(
        runtime=runtime,
        principal=principal,
    )
    return _agent_model_router_decisions_response(runtime=scoped_runtime, limit=limit)


@router.get("/v1/agent/self-repair/failures", response_model=AgentSelfRepairFailureListResponse)
def list_agent_self_repair_failures(
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentSelfRepairFailureListResponse:
    scoped_runtime = _governance_list_runtime(
        runtime=runtime,
        principal=principal,
    )
    return _agent_self_repair_failures_response(runtime=scoped_runtime, limit=limit)


@router.post(
    "/v1/agent/self-repair/promote-preview", response_model=AgentSelfRepairPromotePreviewResponse
)
def preview_agent_self_repair_promotion(
    payload: AgentSelfRepairPromotePreviewRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentSelfRepairPromotePreviewResponse:
    del principal, runtime
    return _agent_self_repair_preview_response(payload)


@router.get("/v1/agent/review-queue", response_model=AgentReviewQueueListResponse)
def list_agent_review_queue(
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentReviewQueueListResponse:
    scoped_runtime = _governance_list_runtime(
        runtime=runtime,
        principal=principal,
    )
    return _agent_review_queue_response(runtime=scoped_runtime, limit=limit)


@router.post(
    "/v1/agent/review-queue/{item_id}/approve", response_model=AgentReviewQueueDecisionResponse
)
def approve_agent_review_queue_item(
    item_id: str,
    principal: Principal = Depends(get_current_principal),
) -> AgentReviewQueueDecisionResponse:
    del principal
    return _agent_review_queue_decision_response(item_id=item_id, approved=True)


@router.post(
    "/v1/agent/review-queue/{item_id}/reject", response_model=AgentReviewQueueDecisionResponse
)
def reject_agent_review_queue_item(
    item_id: str,
    principal: Principal = Depends(get_current_principal),
) -> AgentReviewQueueDecisionResponse:
    del principal
    return _agent_review_queue_decision_response(item_id=item_id, approved=False)


@router.get("/v1/agent/context/policy", response_model=AgentContextPolicyResponse)
def get_agent_context_policy(
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentContextPolicyResponse:
    del principal
    return _agent_context_policy_response(runtime.settings)


@router.post("/v1/agent/context/preview", response_model=AgentContextPreviewResponse)
def preview_agent_context(
    payload: AgentContextPreviewRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentContextPreviewResponse:
    del principal
    return _agent_context_preview_response(payload=payload, runtime=runtime)


@router.get("/v1/agent/context/decisions", response_model=AgentContextDecisionListResponse)
def list_agent_context_decisions(
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentContextDecisionListResponse:
    scoped_runtime = _governance_list_runtime(
        runtime=runtime,
        principal=principal,
    )
    return _agent_context_decisions_response(runtime=scoped_runtime, limit=limit)


@router.get("/v1/agent/context/artifacts", response_model=AgentContextArtifactListResponse)
def list_agent_context_artifacts(
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentContextArtifactListResponse:
    scoped_runtime = _governance_list_runtime(
        runtime=runtime,
        principal=principal,
    )
    return _agent_context_artifacts_response(runtime=scoped_runtime, limit=limit)


@router.get("/v1/agent/context/evidence", response_model=AgentContextEvidenceListResponse)
def list_agent_context_evidence(
    thread_id: str | None = Query(default=None),
    turn_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentContextEvidenceListResponse:
    return _agent_context_evidence_list_response(
        runtime=runtime,
        principal=principal,
        thread_id=thread_id,
        turn_id=turn_id,
        limit=limit,
    )


@router.post("/v1/agent/context/explain", response_model=AgentContextExplainResponse)
def explain_agent_context(
    payload: AgentContextExplainRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentContextExplainResponse:
    return _agent_context_explain_response(
        payload=payload,
        runtime=runtime,
        principal=principal,
    )


@router.get("/v1/agent/task-ledger/policy", response_model=AgentTaskLedgerPolicyResponse)
def get_agent_task_ledger_policy(
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTaskLedgerPolicyResponse:
    del principal
    return _agent_task_ledger_policy_response(runtime.settings)


@router.post("/v1/agent/task-ledger/plan", response_model=AgentTaskLedgerPlanResponse)
def plan_agent_task_ledger(
    payload: AgentTaskLedgerPlanRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTaskLedgerPlanResponse:
    del principal
    return _agent_task_ledger_plan_response(payload=payload, runtime=runtime)


@router.get("/v1/agent/task-ledger/runs", response_model=AgentTaskLedgerRunListResponse)
def list_agent_task_ledger_runs(
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTaskLedgerRunListResponse:
    scoped_runtime = _governance_list_runtime(
        runtime=runtime,
        principal=principal,
    )
    return _agent_task_ledger_runs_response(runtime=scoped_runtime, limit=limit)


@router.get("/v1/agent/artifacts", response_model=AgentArtifactListResponse)
def list_agent_artifacts(
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentArtifactListResponse:
    scoped_runtime = _governance_list_runtime(
        runtime=runtime,
        principal=principal,
    )
    return _agent_artifacts_response(runtime=scoped_runtime, limit=limit)


@router.post("/v1/agent/artifacts/synthesize", response_model=AgentArtifactSynthesisResponse)
def synthesize_agent_artifacts(
    payload: AgentArtifactSynthesisRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentArtifactSynthesisResponse:
    del principal
    return _agent_artifact_synthesis_response_with_runtime(payload=payload, runtime=runtime)


@router.get("/v1/agent/critic/verdicts", response_model=AgentCriticVerdictListResponse)
def list_agent_critic_verdicts(
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentCriticVerdictListResponse:
    scoped_runtime = _governance_list_runtime(
        runtime=runtime,
        principal=principal,
    )
    return _agent_critic_verdicts_response(runtime=scoped_runtime, limit=limit)


@router.post("/v1/agent/critic/evaluate", response_model=AgentCriticEvaluateResponse)
def evaluate_agent_critic_gate(
    payload: AgentCriticEvaluateRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentCriticEvaluateResponse:
    del principal
    return _agent_critic_evaluate_response(payload=payload, runtime=runtime)
