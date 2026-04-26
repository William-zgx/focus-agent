from __future__ import annotations

# ruff: noqa: F403, F405
from ..route_helpers import *

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
    available_tools = payload.available_tools or _available_tool_names(runtime)
    plan = build_role_route_plan(
        settings=runtime.settings,
        task_text=payload.message,
        available_tool_names=available_tools,
        tool_policy=payload.scene,
    )
    return AgentRoleDryRunResponse(
        policy=_agent_role_policy_response(runtime.settings),
        plan=plan.model_dump(mode="json"),
    )

@router.get('/v1/agent/roles/decisions', response_model=AgentRoleDecisionListResponse)
def list_agent_role_decisions(
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentRoleDecisionListResponse:
    del principal
    repo = _maybe_get_trajectory_repository(runtime)
    if repo is None:
        return AgentRoleDecisionListResponse(
            items=[],
            count=0,
            trajectory_available=False,
        )
    try:
        rows = repo.list_turns(TrajectoryTurnQuery(limit=limit, newest_first=True))
    except Exception as exc:  # noqa: BLE001
        return AgentRoleDecisionListResponse(
            items=[],
            count=0,
            trajectory_available=False,
            trajectory_error=str(exc),
        )
    items = _role_route_decision_items(rows)
    return AgentRoleDecisionListResponse(
        items=items,
        count=len(items),
        trajectory_available=True,
    )

@router.get('/v1/agent/capabilities', response_model=AgentCapabilityListResponse)
def list_agent_capabilities(
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentCapabilityListResponse:
    del principal
    registry = getattr(runtime, "tool_registry", None)
    items = build_capability_registry(registry) if registry is not None else []
    return AgentCapabilityListResponse(
        items=[item.model_dump(mode="json") for item in items],
        count=len(items),
    )

@router.post('/v1/agent/tool-router/route', response_model=AgentToolRouteResponse)
def route_agent_tools(
    payload: AgentToolRouteRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentToolRouteResponse:
    del principal
    registry = getattr(runtime, "tool_registry", None)
    if registry is None:
        raise HTTPException(status_code=503, detail="Tool registry is unavailable.")
    plan = build_tool_route_plan(
        tool_registry=registry,
        role=payload.role,
        tool_policy=payload.tool_policy,
        available_tool_names=payload.available_tools or _available_tool_names(runtime),
        enforce=(
            bool(getattr(runtime.settings, "agent_tool_router_enforce", True))
            if payload.enforce is None
            else bool(payload.enforce)
        ),
    )
    return AgentToolRouteResponse(plan=plan.model_dump(mode="json"))

@router.get('/v1/agent/tool-router/decisions', response_model=AgentToolRouteDecisionListResponse)
def list_agent_tool_route_decisions(
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentToolRouteDecisionListResponse:
    del principal
    items, available, error = _list_plan_meta_decisions(runtime=runtime, key="tool_route_plan", limit=limit)
    return AgentToolRouteDecisionListResponse(
        items=items,
        count=len(items),
        trajectory_available=available,
        trajectory_error=error,
    )

@router.get('/v1/agent/memory/curator/policy', response_model=AgentMemoryCuratorPolicyResponse)
def get_agent_memory_curator_policy(
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentMemoryCuratorPolicyResponse:
    del principal
    return AgentMemoryCuratorPolicyResponse(
        enabled=bool(getattr(runtime.settings, "agent_memory_curator_enabled", False)),
        auto_promote_on_merge=bool(getattr(runtime.settings, "agent_memory_auto_promote_on_merge", True)),
    )

@router.post('/v1/agent/memory/curator/evaluate', response_model=AgentMemoryCuratorEvaluateResponse)
def evaluate_agent_memory_curator(
    payload: AgentMemoryCuratorEvaluateRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentMemoryCuratorEvaluateResponse:
    branch_record = BranchRecord(
        branch_id=payload.branch_id,
        root_thread_id=payload.root_thread_id,
        parent_thread_id=payload.parent_thread_id or payload.root_thread_id,
        child_thread_id=payload.child_thread_id or payload.branch_id,
        return_thread_id=payload.parent_thread_id or payload.root_thread_id,
        owner_user_id=payload.user_id or principal.user_id,
        branch_name=payload.branch_name,
        branch_role=BranchRole(payload.branch_role),
        branch_depth=1,
        branch_status=BranchStatus(payload.branch_status),
    )
    context = RequestContext(
        user_id=payload.user_id or principal.user_id,
        root_thread_id=payload.root_thread_id,
        parent_thread_id=payload.parent_thread_id or payload.root_thread_id,
        branch_id=payload.branch_id,
        branch_role=payload.branch_role,
    )
    curator = MemoryCurator(store=getattr(runtime, "store", None))
    decision = curator.evaluate_branch_promotion(
        branch_record=branch_record,
        findings=payload.findings,
        context=context,
        auto_promote=(
            bool(getattr(runtime.settings, "agent_memory_auto_promote_on_merge", True))
            if payload.auto_promote is None
            else bool(payload.auto_promote)
        ),
    )
    return AgentMemoryCuratorEvaluateResponse(decision=decision.model_dump(mode="json"))

@router.get('/v1/agent/memory/curator/decisions', response_model=AgentMemoryCuratorDecisionListResponse)
def list_agent_memory_curator_decisions(
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentMemoryCuratorDecisionListResponse:
    del principal
    items, available, error = _list_plan_meta_decisions(
        runtime=runtime,
        key="memory_curator_decision",
        limit=limit,
    )
    return AgentMemoryCuratorDecisionListResponse(
        items=items,
        count=len(items),
        trajectory_available=available,
        trajectory_error=error,
    )

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
    available_tools = payload.available_tools or _available_tool_names(runtime)
    role_route = build_role_route_plan(
        settings=runtime.settings,
        task_text=payload.message,
        available_tool_names=available_tools,
        tool_policy=payload.scene,
    )
    plan = build_agent_delegation_plan(
        settings=runtime.settings,
        task_text=payload.message,
        role_route_plan=role_route.model_dump(mode="json"),
        available_tool_names=available_tools,
        tool_policy=payload.scene,
    )
    return AgentDelegationPlanResponse(
        policy=_agent_delegation_policy_response(runtime.settings),
        plan=plan.model_dump(mode="json"),
    )

@router.get('/v1/agent/delegation/runs', response_model=AgentDelegationRunListResponse)
def list_agent_delegation_runs(
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentDelegationRunListResponse:
    del principal
    items, available, error = _list_plan_meta_list_items(
        runtime=runtime,
        key="agent_runs",
        limit=limit,
    )
    if not items:
        items, available, error = _list_plan_meta_list_items(
            runtime=runtime,
            key="agent_delegation_plan.runs",
            limit=limit,
        )
    return AgentDelegationRunListResponse(
        items=items,
        count=len(items),
        trajectory_available=available,
        trajectory_error=error,
    )

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
    decision = build_model_route_decision(
        settings=runtime.settings,
        role=payload.role,
        selected_model=payload.selected_model,
        task_text=payload.task_text,
        tool_risk=payload.tool_risk,
        context_size=payload.context_size,
    )
    return AgentModelRouteResponse(decision=decision.model_dump(mode="json"))

@router.get('/v1/agent/model-router/decisions', response_model=AgentModelRouterDecisionListResponse)
def list_agent_model_router_decisions(
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentModelRouterDecisionListResponse:
    del principal
    items, available, error = _list_plan_meta_decisions(
        runtime=runtime,
        key="model_route_decision",
        limit=limit,
    )
    return AgentModelRouterDecisionListResponse(
        items=items,
        count=len(items),
        trajectory_available=available,
        trajectory_error=error,
    )

@router.get('/v1/agent/self-repair/failures', response_model=AgentSelfRepairFailureListResponse)
def list_agent_self_repair_failures(
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentSelfRepairFailureListResponse:
    del principal
    items, available, error = _list_plan_meta_list_items(
        runtime=runtime,
        key="agent_failure_records",
        limit=limit,
    )
    return AgentSelfRepairFailureListResponse(
        items=items,
        count=len(items),
        trajectory_available=available,
        trajectory_error=error,
    )

@router.post('/v1/agent/self-repair/promote-preview', response_model=AgentSelfRepairPromotePreviewResponse)
def preview_agent_self_repair_promotion(
    payload: AgentSelfRepairPromotePreviewRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentSelfRepairPromotePreviewResponse:
    del principal, runtime
    preview = build_self_repair_preview(
        failures=payload.failures,
        case_id_prefix=payload.case_id_prefix,
    )
    return AgentSelfRepairPromotePreviewResponse(preview=preview.model_dump(mode="json"))

@router.get('/v1/agent/review-queue', response_model=AgentReviewQueueListResponse)
def list_agent_review_queue(
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentReviewQueueListResponse:
    del principal
    items, available, error = _list_plan_meta_list_items(
        runtime=runtime,
        key="agent_review_queue",
        limit=limit,
    )
    return AgentReviewQueueListResponse(
        items=items,
        count=len(items),
        trajectory_available=available,
        trajectory_error=error,
    )

@router.post('/v1/agent/review-queue/{item_id}/approve', response_model=AgentReviewQueueDecisionResponse)
def approve_agent_review_queue_item(
    item_id: str,
    principal: Principal = Depends(get_current_principal),
) -> AgentReviewQueueDecisionResponse:
    del principal
    item = apply_review_decision({"item_id": item_id, "item_type": "manual", "summary": "Approved by operator."}, approved=True)
    return AgentReviewQueueDecisionResponse(item=item.model_dump(mode="json"))

@router.post('/v1/agent/review-queue/{item_id}/reject', response_model=AgentReviewQueueDecisionResponse)
def reject_agent_review_queue_item(
    item_id: str,
    principal: Principal = Depends(get_current_principal),
) -> AgentReviewQueueDecisionResponse:
    del principal
    item = apply_review_decision({"item_id": item_id, "item_type": "manual", "summary": "Rejected by operator."}, approved=False)
    return AgentReviewQueueDecisionResponse(item=item.model_dump(mode="json"))

@router.get('/v1/agent/context/policy', response_model=AgentContextPolicyResponse)
def get_agent_context_policy(
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentContextPolicyResponse:
    del principal
    return AgentContextPolicyResponse(**build_context_policy(runtime.settings))

@router.post('/v1/agent/context/preview', response_model=AgentContextPreviewResponse)
def preview_agent_context(
    payload: AgentContextPreviewRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentContextPreviewResponse:
    del principal
    decision = build_context_engineering_decision(
        settings=runtime.settings,
        state=dict(payload.state or {}),
        prompt_mode=payload.prompt_mode,
        assembled_context=payload.assembled_context,
        role=payload.role,
        artifact_dir=runtime.settings.artifact_dir,
        materialize=payload.materialize_artifacts,
    )
    return AgentContextPreviewResponse(decision=decision.model_dump(mode="json"))

@router.get('/v1/agent/context/decisions', response_model=AgentContextDecisionListResponse)
def list_agent_context_decisions(
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentContextDecisionListResponse:
    del principal
    items, available, error = _list_plan_meta_decisions(
        runtime=runtime,
        key="context_budget_decision",
        limit=limit,
    )
    return AgentContextDecisionListResponse(
        items=items,
        count=len(items),
        trajectory_available=available,
        trajectory_error=error,
    )

@router.get('/v1/agent/context/artifacts', response_model=AgentContextArtifactListResponse)
def list_agent_context_artifacts(
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentContextArtifactListResponse:
    del principal
    items, available, error = _list_plan_meta_list_items(
        runtime=runtime,
        key="context_artifact_refs",
        limit=limit,
    )
    return AgentContextArtifactListResponse(
        items=items,
        count=len(items),
        trajectory_available=available,
        trajectory_error=error,
    )

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
    delegation_plan = dict(payload.delegation_plan or {})
    if not delegation_plan and payload.message:
        available_tools = _available_tool_names(runtime)
        role_route = build_role_route_plan(
            settings=runtime.settings,
            task_text=payload.message,
            available_tool_names=available_tools,
            tool_policy="agent_task_ledger_console",
        )
        delegation_plan = build_agent_delegation_plan(
            settings=runtime.settings,
            task_text=payload.message,
            role_route_plan=role_route.model_dump(mode="json"),
            available_tool_names=available_tools,
            tool_policy="agent_task_ledger_console",
        ).model_dump(mode="json")
    ledger = build_agent_task_ledger(
        settings=runtime.settings,
        delegation_plan=delegation_plan,
    ).model_dump(mode="json")
    artifacts = [
        item.model_dump(mode="json")
        for item in build_delegated_artifacts(
            ledger=ledger,
            delegation_plan=delegation_plan,
        )
    ]
    critic_result = (
        evaluate_critic_gate(
            settings=runtime.settings,
            ledger=ledger,
            artifacts=artifacts,
        ).model_dump(mode="json")
        if getattr(runtime.settings, "agent_critic_gate_enabled", False)
        else None
    )
    synthesis_result = (
        synthesize_delegated_artifacts(
            settings=runtime.settings,
            artifacts=artifacts,
            critic_gate_result=critic_result,
        ).model_dump(mode="json")
        if getattr(runtime.settings, "agent_artifact_synthesis_enabled", False)
        else None
    )
    return AgentTaskLedgerPlanResponse(
        policy=_agent_task_ledger_policy_response(runtime.settings),
        ledger=ledger,
        artifacts=artifacts,
        critic_gate_result=critic_result,
        synthesis_result=synthesis_result,
    )

@router.get('/v1/agent/task-ledger/runs', response_model=AgentTaskLedgerRunListResponse)
def list_agent_task_ledger_runs(
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTaskLedgerRunListResponse:
    del principal
    items, available, error = _list_plan_meta_list_items(
        runtime=runtime,
        key="agent_task_ledger.tasks",
        limit=limit,
    )
    return AgentTaskLedgerRunListResponse(
        items=items,
        count=len(items),
        trajectory_available=available,
        trajectory_error=error,
    )

@router.get('/v1/agent/artifacts', response_model=AgentArtifactListResponse)
def list_agent_artifacts(
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentArtifactListResponse:
    del principal
    items, available, error = _list_plan_meta_list_items(
        runtime=runtime,
        key="delegated_artifacts",
        limit=limit,
    )
    return AgentArtifactListResponse(
        items=items,
        count=len(items),
        trajectory_available=available,
        trajectory_error=error,
    )

@router.post('/v1/agent/artifacts/synthesize', response_model=AgentArtifactSynthesisResponse)
def synthesize_agent_artifacts(
    payload: AgentArtifactSynthesisRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentArtifactSynthesisResponse:
    del principal
    result = synthesize_delegated_artifacts(
        settings=runtime.settings,
        artifacts=payload.artifacts,
        critic_gate_result=payload.critic_gate_result,
    )
    return AgentArtifactSynthesisResponse(result=result.model_dump(mode="json"))

@router.get('/v1/agent/critic/verdicts', response_model=AgentCriticVerdictListResponse)
def list_agent_critic_verdicts(
    limit: int = Query(default=50, ge=0, le=200),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentCriticVerdictListResponse:
    del principal
    items, available, error = _list_plan_meta_decisions(
        runtime=runtime,
        key="critic_gate_result",
        limit=limit,
    )
    return AgentCriticVerdictListResponse(
        items=items,
        count=len(items),
        trajectory_available=available,
        trajectory_error=error,
    )

@router.post('/v1/agent/critic/evaluate', response_model=AgentCriticEvaluateResponse)
def evaluate_agent_critic_gate(
    payload: AgentCriticEvaluateRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentCriticEvaluateResponse:
    del principal
    result = evaluate_critic_gate(
        settings=runtime.settings,
        ledger=payload.ledger,
        artifacts=payload.artifacts,
    )
    return AgentCriticEvaluateResponse(result=result.model_dump(mode="json"))
