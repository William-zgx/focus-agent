from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from focus_agent.core.users import UserStatus
from focus_agent.engine.runtime import AppRuntime
from focus_agent.security.permissions import is_admin_role, permissions_for_roles
from focus_agent.security.tokens import Principal

from ..contracts import (
    AgentArtifactListResponse,
    AgentCapabilityListResponse,
    AgentContextArtifactListResponse,
    AgentContextDecisionListResponse,
    AgentContextEvidenceListResponse,
    AgentContextExplainRequest,
    AgentContextExplainResponse,
    AgentContextPolicyResponse,
    AgentContextPreviewRequest,
    AgentContextPreviewResponse,
    AgentFeedbackTrendResponse,
    AgentMemoryCuratorDecisionListResponse,
    AgentMemoryCuratorEvaluateRequest,
    AgentMemoryCuratorEvaluateResponse,
    AgentMemoryCuratorPolicyResponse,
    AgentSkillCatalogResponse,
    AgentSkillPreferenceRequest,
    AgentSkillPreferenceResponse,
    AgentSkillSelectionEventListResponse,
    AgentSkillSelectionFeedbackRequest,
    AgentSkillSelectionFeedbackResponse,
    AgentSkillSelectionResponse,
    AgentSkillSelectRequest,
    AgentSkillSemanticCandidateResponse,
    AgentToolsetListResponse,
)
from ..deps import get_app_runtime, get_current_principal
from ..route_utils.agent_governance import (
    _agent_artifacts_response,
    _agent_capabilities_response,
    _agent_context_artifacts_response,
    _agent_context_decisions_response,
    _agent_context_policy_response,
    _agent_context_preview_response,
    _agent_memory_curator_decisions_response,
    _agent_memory_curator_evaluate_response,
    _agent_memory_curator_policy_response,
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
from ..route_utils.pagination import PageLimit

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
    limit: PageLimit = 50,
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
    limit: PageLimit = 50,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentMemoryCuratorDecisionListResponse:
    scoped_runtime = _governance_list_runtime(
        runtime=runtime,
        principal=principal,
    )
    return _agent_memory_curator_decisions_response(runtime=scoped_runtime, limit=limit)


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
    limit: PageLimit = 50,
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
    limit: PageLimit = 50,
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
    limit: PageLimit = 50,
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


@router.get("/v1/agent/artifacts", response_model=AgentArtifactListResponse)
def list_agent_artifacts(
    limit: PageLimit = 50,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentArtifactListResponse:
    scoped_runtime = _governance_list_runtime(
        runtime=runtime,
        principal=principal,
    )
    return _agent_artifacts_response(runtime=scoped_runtime, limit=limit)
