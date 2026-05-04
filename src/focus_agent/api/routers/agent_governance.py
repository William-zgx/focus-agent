from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from focus_agent.engine.runtime import AppRuntime
from focus_agent.security.tokens import Principal

from ..contracts import (
    AgentArtifactListResponse,
    AgentArtifactSynthesisRequest,
    AgentArtifactSynthesisResponse,
    AgentCapabilityListResponse,
    AgentContextArtifactListResponse,
    AgentContextDecisionListResponse,
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
    AgentMemoryCuratorDecisionListResponse,
    AgentMemoryCuratorEvaluateRequest,
    AgentMemoryCuratorEvaluateResponse,
    AgentMemoryCuratorPolicyResponse,
    AgentModelRouteRequest,
    AgentModelRouteResponse,
    AgentModelRouterDecisionListResponse,
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
    AgentTaskLedgerPlanRequest,
    AgentTaskLedgerPlanResponse,
    AgentTaskLedgerPolicyResponse,
    AgentTaskLedgerRunListResponse,
    AgentToolRouteDecisionListResponse,
    AgentToolRouteRequest,
    AgentToolRouteResponse,
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
)

router = APIRouter()


@router.get('/v1/agent/roles/policy', response_model=AgentRolePolicyResponse)
def get_agent_role_policy(
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentRolePolicyResponse:
    del principal
    return _agent_role_policy_response(runtime.settings)

@router.post('/v1/agent/roles/dry-run', response_model=AgentRoleDryRunResponse)
def dry_run_agent_role_route(
    payload: AgentRoleDryRunRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentRoleDryRunResponse:
    del principal
    return _agent_role_dry_run_response(payload=payload, runtime=runtime)

@router.get('/v1/agent/roles/decisions', response_model=AgentRoleDecisionListResponse)
def list_agent_role_decisions(
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentRoleDecisionListResponse:
    del principal
    return _agent_role_decisions_response(runtime=runtime, limit=limit)

@router.get('/v1/agent/capabilities', response_model=AgentCapabilityListResponse)
def list_agent_capabilities(
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentCapabilityListResponse:
    del principal
    return _agent_capabilities_response(runtime)

@router.post('/v1/agent/tool-router/route', response_model=AgentToolRouteResponse)
def route_agent_tools(
    payload: AgentToolRouteRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentToolRouteResponse:
    del principal
    return _agent_tool_route_response(payload=payload, runtime=runtime)

@router.get('/v1/agent/tool-router/decisions', response_model=AgentToolRouteDecisionListResponse)
def list_agent_tool_route_decisions(
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentToolRouteDecisionListResponse:
    del principal
    return _agent_tool_route_decisions_response(runtime=runtime, limit=limit)

@router.get('/v1/agent/memory/curator/policy', response_model=AgentMemoryCuratorPolicyResponse)
def get_agent_memory_curator_policy(
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentMemoryCuratorPolicyResponse:
    del principal
    return _agent_memory_curator_policy_response(runtime.settings)

@router.post('/v1/agent/memory/curator/evaluate', response_model=AgentMemoryCuratorEvaluateResponse)
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

@router.get('/v1/agent/memory/curator/decisions', response_model=AgentMemoryCuratorDecisionListResponse)
def list_agent_memory_curator_decisions(
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentMemoryCuratorDecisionListResponse:
    del principal
    return _agent_memory_curator_decisions_response(runtime=runtime, limit=limit)

@router.get('/v1/agent/delegation/policy', response_model=AgentDelegationPolicyResponse)
def get_agent_delegation_policy(
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentDelegationPolicyResponse:
    del principal
    return _agent_delegation_policy_response(runtime.settings)

@router.post('/v1/agent/delegation/plan', response_model=AgentDelegationPlanResponse)
def plan_agent_delegation(
    payload: AgentDelegationPlanRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentDelegationPlanResponse:
    del principal
    return _agent_delegation_plan_response(payload=payload, runtime=runtime)

@router.get('/v1/agent/delegation/runs', response_model=AgentDelegationRunListResponse)
def list_agent_delegation_runs(
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentDelegationRunListResponse:
    del principal
    return _agent_delegation_runs_response(runtime=runtime, limit=limit)

@router.get('/v1/agent/model-router/policy', response_model=AgentModelRouterPolicyResponse)
def get_agent_model_router_policy(
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentModelRouterPolicyResponse:
    del principal
    return _agent_model_router_policy_response(runtime.settings)

@router.post('/v1/agent/model-router/route', response_model=AgentModelRouteResponse)
def route_agent_model(
    payload: AgentModelRouteRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentModelRouteResponse:
    del principal
    return _agent_model_route_response(payload=payload, runtime=runtime)

@router.get('/v1/agent/model-router/decisions', response_model=AgentModelRouterDecisionListResponse)
def list_agent_model_router_decisions(
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentModelRouterDecisionListResponse:
    del principal
    return _agent_model_router_decisions_response(runtime=runtime, limit=limit)

@router.get('/v1/agent/self-repair/failures', response_model=AgentSelfRepairFailureListResponse)
def list_agent_self_repair_failures(
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentSelfRepairFailureListResponse:
    del principal
    return _agent_self_repair_failures_response(runtime=runtime, limit=limit)

@router.post('/v1/agent/self-repair/promote-preview', response_model=AgentSelfRepairPromotePreviewResponse)
def preview_agent_self_repair_promotion(
    payload: AgentSelfRepairPromotePreviewRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentSelfRepairPromotePreviewResponse:
    del principal, runtime
    return _agent_self_repair_preview_response(payload)

@router.get('/v1/agent/review-queue', response_model=AgentReviewQueueListResponse)
def list_agent_review_queue(
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentReviewQueueListResponse:
    del principal
    return _agent_review_queue_response(runtime=runtime, limit=limit)

@router.post('/v1/agent/review-queue/{item_id}/approve', response_model=AgentReviewQueueDecisionResponse)
def approve_agent_review_queue_item(
    item_id: str,
    principal: Principal = Depends(get_current_principal),
) -> AgentReviewQueueDecisionResponse:
    del principal
    return _agent_review_queue_decision_response(item_id=item_id, approved=True)

@router.post('/v1/agent/review-queue/{item_id}/reject', response_model=AgentReviewQueueDecisionResponse)
def reject_agent_review_queue_item(
    item_id: str,
    principal: Principal = Depends(get_current_principal),
) -> AgentReviewQueueDecisionResponse:
    del principal
    return _agent_review_queue_decision_response(item_id=item_id, approved=False)

@router.get('/v1/agent/context/policy', response_model=AgentContextPolicyResponse)
def get_agent_context_policy(
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentContextPolicyResponse:
    del principal
    return _agent_context_policy_response(runtime.settings)

@router.post('/v1/agent/context/preview', response_model=AgentContextPreviewResponse)
def preview_agent_context(
    payload: AgentContextPreviewRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentContextPreviewResponse:
    del principal
    return _agent_context_preview_response(payload=payload, runtime=runtime)

@router.get('/v1/agent/context/decisions', response_model=AgentContextDecisionListResponse)
def list_agent_context_decisions(
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentContextDecisionListResponse:
    del principal
    return _agent_context_decisions_response(runtime=runtime, limit=limit)

@router.get('/v1/agent/context/artifacts', response_model=AgentContextArtifactListResponse)
def list_agent_context_artifacts(
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentContextArtifactListResponse:
    del principal
    return _agent_context_artifacts_response(runtime=runtime, limit=limit)

@router.get('/v1/agent/task-ledger/policy', response_model=AgentTaskLedgerPolicyResponse)
def get_agent_task_ledger_policy(
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTaskLedgerPolicyResponse:
    del principal
    return _agent_task_ledger_policy_response(runtime.settings)

@router.post('/v1/agent/task-ledger/plan', response_model=AgentTaskLedgerPlanResponse)
def plan_agent_task_ledger(
    payload: AgentTaskLedgerPlanRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTaskLedgerPlanResponse:
    del principal
    return _agent_task_ledger_plan_response(payload=payload, runtime=runtime)

@router.get('/v1/agent/task-ledger/runs', response_model=AgentTaskLedgerRunListResponse)
def list_agent_task_ledger_runs(
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTaskLedgerRunListResponse:
    del principal
    return _agent_task_ledger_runs_response(runtime=runtime, limit=limit)

@router.get('/v1/agent/artifacts', response_model=AgentArtifactListResponse)
def list_agent_artifacts(
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentArtifactListResponse:
    del principal
    return _agent_artifacts_response(runtime=runtime, limit=limit)

@router.post('/v1/agent/artifacts/synthesize', response_model=AgentArtifactSynthesisResponse)
def synthesize_agent_artifacts(
    payload: AgentArtifactSynthesisRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentArtifactSynthesisResponse:
    del principal
    return _agent_artifact_synthesis_response_with_runtime(payload=payload, runtime=runtime)

@router.get('/v1/agent/critic/verdicts', response_model=AgentCriticVerdictListResponse)
def list_agent_critic_verdicts(
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentCriticVerdictListResponse:
    del principal
    return _agent_critic_verdicts_response(runtime=runtime, limit=limit)

@router.post('/v1/agent/critic/evaluate', response_model=AgentCriticEvaluateResponse)
def evaluate_agent_critic_gate(
    payload: AgentCriticEvaluateRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentCriticEvaluateResponse:
    del principal
    return _agent_critic_evaluate_response(payload=payload, runtime=runtime)
