from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response

from focus_agent.engine.runtime import AppRuntime
from focus_agent.security.tokens import Principal

from ..contract_models.agent_team import (
    AgentTeamMergeReviewCaptureResponse,
    AgentTeamMergeReviewListResponse,
    AgentTeamMergeReviewResponse,
    AgentTeamToolApprovalActionRequest,
    AgentTeamToolApprovalContract,
    AgentTeamToolApprovalDecisionResponse,
    AgentTeamToolApprovalListResponse,
    ApplyAgentTeamMergeReviewRequest,
    CreateAgentTeamMergeReviewRequest,
    DecideAgentTeamToolApprovalRequest,
    RejectAgentTeamMergeReviewRequest,
    UpdateAgentTeamMergeReviewRequest,
)
from ..contracts import (
    AgentTeamDispatchResponse,
    AgentTeamMergeBundleResponse,
    AgentTeamMergeDecisionResponse,
    AgentTeamPlanningMetadata,
    AgentTeamPlanSessionRequest,
    AgentTeamSessionListResponse,
    AgentTeamSessionResponse,
    AgentTeamSessionViewResponse,
    AgentTeamTaskListResponse,
    AgentTeamTaskOutputResponse,
    AgentTeamTaskResponse,
    ApplyAgentTeamMergeDecisionRequest,
    CreateAgentTeamSessionRequest,
    CreateAgentTeamTaskRequest,
    DispatchAgentTeamSessionRequest,
    RecordAgentTeamTaskOutputRequest,
    RunAgentTeamSessionRequest,
    UpdateAgentTeamTaskRequest,
)
from ..deps import get_app_runtime, get_current_principal
from ..route_utils.agent_team import _agent_team_error, _agent_team_service_or_503
from ..route_utils.agent_team_responses import (
    _DEPRECATED_ROUTE_LINK_REL,
    _call_plan_session,
    _mark_deprecated_route,
    _model_payload,
    _planning_metadata_payload,
    _view_response,
)

router = APIRouter()


@router.post("/v1/agent-team/sessions", response_model=AgentTeamSessionResponse)
def create_agent_team_session(
    payload: CreateAgentTeamSessionRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamSessionResponse:
    service = _agent_team_service_or_503(runtime)
    try:
        session = service.create_session(
            root_thread_id=payload.root_thread_id,
            user_id=principal.user_id,
            title=payload.title,
            goal=payload.goal,
        )
    except Exception as exc:  # noqa: BLE001
        raise _agent_team_error(exc) from exc
    return AgentTeamSessionResponse(session=session)


@router.get("/v1/agent-team/sessions", response_model=AgentTeamSessionListResponse)
def list_agent_team_sessions(
    root_thread_id: str | None = None,
    status: str | None = None,
    limit: int | None = Query(default=None, ge=0),
    offset: int = Query(default=0, ge=0),
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamSessionListResponse:
    service = _agent_team_service_or_503(runtime)
    try:
        sessions = service.list_sessions(
            user_id=principal.user_id,
            root_thread_id=root_thread_id,
            status=status,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:  # noqa: BLE001
        raise _agent_team_error(exc) from exc
    return AgentTeamSessionListResponse(sessions=sessions, items=sessions, count=len(sessions))


@router.get("/v1/agent-team/sessions/{session_id}", response_model=AgentTeamSessionResponse)
def get_agent_team_session(
    session_id: str,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamSessionResponse:
    service = _agent_team_service_or_503(runtime)
    try:
        session = service.get_session(session_id, user_id=principal.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _agent_team_error(exc) from exc
    return AgentTeamSessionResponse(session=session)


@router.post(
    "/v1/agent-team/sessions/{session_id}/dispatch", response_model=AgentTeamDispatchResponse
)
def dispatch_agent_team_session(
    session_id: str,
    payload: DispatchAgentTeamSessionRequest | None = None,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamDispatchResponse:
    service = _agent_team_service_or_503(runtime)
    request = payload or DispatchAgentTeamSessionRequest()
    try:
        session, tasks = service.dispatch_default_tasks(
            session_id=session_id,
            user_id=principal.user_id,
            create_branches=request.auto_fork_branch
            if request.auto_fork_branch is not None
            else request.create_branches,
            parent_thread_id=request.parent_thread_id,
        )
    except Exception as exc:  # noqa: BLE001
        raise _agent_team_error(exc) from exc
    return AgentTeamDispatchResponse(session=session, tasks=tasks, items=tasks, count=len(tasks))


@router.post("/v1/agent-team/sessions/{session_id}/plan", response_model=AgentTeamDispatchResponse)
def plan_agent_team_session(
    session_id: str,
    payload: AgentTeamPlanSessionRequest | None = None,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamDispatchResponse:
    service = _agent_team_service_or_503(runtime)
    request = payload or AgentTeamPlanSessionRequest()
    create_branches = (
        request.auto_fork_branch
        if request.auto_fork_branch is not None
        else request.create_branches
    )
    try:
        session, tasks = _call_plan_session(
            service,
            session_id=session_id,
            user_id=principal.user_id,
            create_branches=create_branches,
            parent_thread_id=request.parent_thread_id,
            replace_existing=bool(request.replace_existing),
            granularity=request.granularity,
            focus=request.focus,
            max_tasks=request.max_tasks,
        )
    except Exception as exc:  # noqa: BLE001
        raise _agent_team_error(exc) from exc
    planning = AgentTeamPlanningMetadata.model_validate(
        _planning_metadata_payload(
            {"session": session, "tasks": tasks},
            default_source="agent_team_plan",
        )
    )
    return AgentTeamDispatchResponse(
        session=session,
        tasks=tasks,
        items=tasks,
        count=len(tasks),
        planning=planning,
    )


@router.post(
    "/v1/agent-team/sessions/{session_id}/run", response_model=AgentTeamSessionViewResponse
)
def run_agent_team_session(
    session_id: str,
    payload: RunAgentTeamSessionRequest | None = None,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamSessionViewResponse:
    service = _agent_team_service_or_503(runtime)
    try:
        service.run_ready_tasks(
            session_id=session_id,
            user_id=principal.user_id,
            task_ids=payload.task_ids if payload else None,
        )
    except Exception as exc:  # noqa: BLE001
        raise _agent_team_error(exc) from exc
    return _view_response(
        service.get_session_view(session_id=session_id, user_id=principal.user_id)
    )


@router.get(
    "/v1/agent-team/sessions/{session_id}/view", response_model=AgentTeamSessionViewResponse
)
def get_agent_team_session_view(
    session_id: str,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamSessionViewResponse:
    service = _agent_team_service_or_503(runtime)
    try:
        return _view_response(
            service.get_session_view(session_id=session_id, user_id=principal.user_id)
        )
    except Exception as exc:  # noqa: BLE001
        raise _agent_team_error(exc) from exc


@router.get(
    "/v1/agent-team/sessions/{session_id}/tool-approvals",
    response_model=AgentTeamToolApprovalListResponse,
)
def list_agent_team_tool_approvals(
    session_id: str,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamToolApprovalListResponse:
    service = _agent_team_service_or_503(runtime)
    try:
        session = service.get_session(session_id, user_id=principal.user_id)
        approvals = _pending_tool_approvals_for_session(service, session)
    except Exception as exc:  # noqa: BLE001
        raise _agent_team_error(exc) from exc
    return AgentTeamToolApprovalListResponse(
        approvals=approvals,
        items=approvals,
        count=len(approvals),
    )


@router.post(
    "/v1/agent-team/sessions/{session_id}/tool-approvals/{request_id}/decision",
    response_model=AgentTeamToolApprovalDecisionResponse,
)
def decide_agent_team_tool_approval(
    session_id: str,
    request_id: str,
    payload: DecideAgentTeamToolApprovalRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamToolApprovalDecisionResponse:
    service = _agent_team_service_or_503(runtime)
    try:
        session = service.get_session(session_id, user_id=principal.user_id)
        approval_queue = _agent_team_approval_queue(service)
        request = _get_tool_approval_request(approval_queue, request_id)
        if request is None or str(request.session_id) not in {
            session.session_id,
            session.root_thread_id,
        }:
            raise KeyError(request_id)
        approval_queue.decide(
            request_id=request_id,
            approved=payload.approved,
            decided_by=principal.user_id,
        )
        decided = _get_tool_approval_request(approval_queue, request_id) or request
    except Exception as exc:  # noqa: BLE001
        raise _agent_team_error(exc) from exc
    return AgentTeamToolApprovalDecisionResponse(
        approval=AgentTeamToolApprovalContract.model_validate(_tool_approval_payload(decided))
    )


@router.post(
    "/v1/agent-team/sessions/{session_id}/tool-approvals/{request_id}/approve",
    response_model=AgentTeamToolApprovalDecisionResponse,
)
def approve_agent_team_tool_approval(
    session_id: str,
    request_id: str,
    payload: AgentTeamToolApprovalActionRequest | None = None,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamToolApprovalDecisionResponse:
    return decide_agent_team_tool_approval(
        session_id=session_id,
        request_id=request_id,
        payload=DecideAgentTeamToolApprovalRequest(
            approved=True,
            reason=payload.reason if payload else None,
        ),
        principal=principal,
        runtime=runtime,
    )


@router.post(
    "/v1/agent-team/sessions/{session_id}/tool-approvals/{request_id}/reject",
    response_model=AgentTeamToolApprovalDecisionResponse,
)
def reject_agent_team_tool_approval(
    session_id: str,
    request_id: str,
    payload: AgentTeamToolApprovalActionRequest | None = None,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamToolApprovalDecisionResponse:
    return decide_agent_team_tool_approval(
        session_id=session_id,
        request_id=request_id,
        payload=DecideAgentTeamToolApprovalRequest(
            approved=False,
            reason=payload.reason if payload else None,
        ),
        principal=principal,
        runtime=runtime,
    )


@router.post("/v1/agent-team/sessions/{session_id}/tasks", response_model=AgentTeamTaskResponse)
def create_agent_team_task(
    session_id: str,
    payload: CreateAgentTeamTaskRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamTaskResponse:
    service = _agent_team_service_or_503(runtime)
    try:
        task = service.create_task(
            session_id=session_id,
            user_id=principal.user_id,
            role=payload.role,
            goal=payload.goal,
            task_kind=payload.task_kind,
            input_contract=payload.input_contract,
            output_contract=payload.output_contract,
            evidence_required=payload.evidence_required,
            capability_requirements=payload.capability_requirements,
            risk_level=payload.risk_level,
            write_scope=payload.write_scope,
            resource_claims=payload.resource_claims,
            replan_policy=payload.replan_policy,
            scope=payload.scope,
            dependencies=payload.dependencies,
            acceptance_criteria=payload.acceptance_criteria,
            context_refs=payload.context_refs,
            active_skill_ids=payload.active_skill_ids,
            skill_resolution_events=payload.skill_resolution_events,
            create_branch=payload.auto_fork_branch
            if payload.auto_fork_branch is not None
            else payload.create_branch,
            branch_name=payload.branch_name,
            parent_thread_id=payload.parent_thread_id,
        )
    except Exception as exc:  # noqa: BLE001
        raise _agent_team_error(exc) from exc
    return AgentTeamTaskResponse(task=task)


@router.get("/v1/agent-team/sessions/{session_id}/tasks", response_model=AgentTeamTaskListResponse)
def list_agent_team_tasks(
    session_id: str,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamTaskListResponse:
    service = _agent_team_service_or_503(runtime)
    try:
        tasks = service.list_tasks(session_id=session_id, user_id=principal.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _agent_team_error(exc) from exc
    return AgentTeamTaskListResponse(tasks=tasks, items=tasks, count=len(tasks))


@router.get("/v1/agent-team/tasks/{task_id}", response_model=AgentTeamTaskResponse)
def get_agent_team_task(
    task_id: str,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamTaskResponse:
    service = _agent_team_service_or_503(runtime)
    try:
        task = service.get_task(task_id, user_id=principal.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _agent_team_error(exc) from exc
    return AgentTeamTaskResponse(task=task)


@router.patch("/v1/agent-team/tasks/{task_id}", response_model=AgentTeamTaskResponse)
def update_agent_team_task_status(
    task_id: str,
    payload: UpdateAgentTeamTaskRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamTaskResponse:
    return _update_agent_team_task_status(
        task_id=task_id,
        payload=payload,
        principal=principal,
        runtime=runtime,
    )


@router.post(
    "/v1/agent-team/tasks/{task_id}/status",
    response_model=AgentTeamTaskResponse,
    include_in_schema=False,
)
def update_agent_team_task_status_legacy(
    task_id: str,
    payload: UpdateAgentTeamTaskRequest,
    response: Response,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamTaskResponse:
    _mark_deprecated_route(response, canonical_path=f"/v1/agent-team/tasks/{task_id}")
    return _update_agent_team_task_status(
        task_id=task_id,
        payload=payload,
        principal=principal,
        runtime=runtime,
    )


def _update_agent_team_task_status(
    *,
    task_id: str,
    payload: UpdateAgentTeamTaskRequest,
    principal: Principal,
    runtime: AppRuntime,
) -> AgentTeamTaskResponse:
    service = _agent_team_service_or_503(runtime)
    try:
        task = service.update_task(
            task_id=task_id,
            user_id=principal.user_id,
            status=payload.status,
            changed_files=payload.changed_files,
            test_evidence=payload.test_evidence,
            verification_summary=payload.verification_summary,
            risk_notes=payload.risk_notes,
            workspace_id=payload.workspace_id,
            workspace_branch=payload.workspace_branch,
            workspace_path=payload.workspace_path,
            base_commit=payload.base_commit,
            diff_summary=payload.diff_summary,
            workspace_status=payload.workspace_status,
            acceptance_criteria=payload.acceptance_criteria,
            context_refs=payload.context_refs,
            active_skill_ids=payload.active_skill_ids,
            skill_resolution_events=payload.skill_resolution_events,
            dependencies=payload.dependencies,
            input_contract=payload.input_contract,
            output_contract=payload.output_contract,
            evidence_required=payload.evidence_required,
            capability_requirements=payload.capability_requirements,
            risk_level=payload.risk_level,
            write_scope=payload.write_scope,
            resource_claims=payload.resource_claims,
            replan_policy=payload.replan_policy,
            scope=payload.scope,
            run_status=payload.run_status,
            started_at=payload.started_at,
            finished_at=payload.finished_at,
            last_error=payload.last_error,
        )
    except Exception as exc:  # noqa: BLE001
        raise _agent_team_error(exc) from exc
    return AgentTeamTaskResponse(task=task)


@router.post("/v1/agent-team/tasks/{task_id}/run", response_model=AgentTeamTaskResponse)
def run_agent_team_task(
    task_id: str,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamTaskResponse:
    service = _agent_team_service_or_503(runtime)
    try:
        task = service.run_task(task_id=task_id, user_id=principal.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _agent_team_error(exc) from exc
    return AgentTeamTaskResponse(task=task)


@router.post("/v1/agent-team/tasks/{task_id}/retry", response_model=AgentTeamTaskResponse)
def retry_agent_team_task(
    task_id: str,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamTaskResponse:
    service = _agent_team_service_or_503(runtime)
    try:
        task = service.retry_task(task_id=task_id, user_id=principal.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _agent_team_error(exc) from exc
    return AgentTeamTaskResponse(task=task)


@router.post("/v1/agent-team/tasks/{task_id}/cancel", response_model=AgentTeamTaskResponse)
def cancel_agent_team_task(
    task_id: str,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamTaskResponse:
    service = _agent_team_service_or_503(runtime)
    try:
        task = service.cancel_task(task_id=task_id, user_id=principal.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _agent_team_error(exc) from exc
    return AgentTeamTaskResponse(task=task)


@router.post(
    "/v1/agent-team/sessions/{session_id}/cancel", response_model=AgentTeamSessionViewResponse
)
def cancel_agent_team_session(
    session_id: str,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamSessionViewResponse:
    service = _agent_team_service_or_503(runtime)
    try:
        service.cancel_session(session_id=session_id, user_id=principal.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _agent_team_error(exc) from exc
    return _view_response(
        service.get_session_view(session_id=session_id, user_id=principal.user_id)
    )


@router.post("/v1/agent-team/tasks/{task_id}/outputs", response_model=AgentTeamTaskOutputResponse)
def record_agent_team_task_output(
    task_id: str,
    payload: RecordAgentTeamTaskOutputRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamTaskOutputResponse:
    service = _agent_team_service_or_503(runtime)
    try:
        output = service.record_task_output(
            task_id=task_id,
            user_id=principal.user_id,
            kind=payload.kind or payload.artifact_kind or "handoff",
            artifact_id=payload.artifact_id,
            summary=payload.summary or payload.content or "",
            changed_files=payload.changed_files,
            test_evidence=[
                *payload.test_evidence,
                *([payload.verification_summary] if payload.verification_summary else []),
            ],
            workspace_id=payload.workspace_id,
            workspace_branch=payload.workspace_branch,
            workspace_path=payload.workspace_path,
            base_commit=payload.base_commit,
            diff_summary=payload.diff_summary,
            workspace_status=payload.workspace_status,
            risk_notes=payload.risk_notes,
            metadata=payload.metadata,
        )
    except Exception as exc:  # noqa: BLE001
        raise _agent_team_error(exc) from exc
    task = service.get_task(task_id, user_id=principal.user_id)
    return AgentTeamTaskOutputResponse(output=output, task=task)


@router.post(
    "/v1/agent-team/sessions/{session_id}/merge-bundle", response_model=AgentTeamMergeBundleResponse
)
def prepare_agent_team_merge_bundle(
    session_id: str,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamMergeBundleResponse:
    return _prepare_agent_team_merge_bundle(
        session_id=session_id,
        principal=principal,
        runtime=runtime,
    )


@router.post(
    "/v1/agent-team/sessions/{session_id}/merge-proposal",
    response_model=AgentTeamMergeBundleResponse,
    include_in_schema=False,
)
def prepare_agent_team_merge_bundle_legacy(
    session_id: str,
    response: Response,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamMergeBundleResponse:
    _mark_deprecated_route(
        response,
        canonical_path=f"/v1/agent-team/sessions/{session_id}/merge-bundle",
    )
    return _prepare_agent_team_merge_bundle(
        session_id=session_id,
        principal=principal,
        runtime=runtime,
    )


def _prepare_agent_team_merge_bundle(
    *,
    session_id: str,
    principal: Principal,
    runtime: AppRuntime,
) -> AgentTeamMergeBundleResponse:
    service = _agent_team_service_or_503(runtime)
    try:
        bundle = service.prepare_merge_bundle(session_id=session_id, user_id=principal.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _agent_team_error(exc) from exc
    return AgentTeamMergeBundleResponse(bundle=bundle)


@router.post(
    "/v1/agent-team/sessions/{session_id}/merge-decision",
    response_model=AgentTeamMergeDecisionResponse,
)
def apply_agent_team_merge_decision(
    session_id: str,
    payload: ApplyAgentTeamMergeDecisionRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamMergeDecisionResponse:
    return _apply_agent_team_merge_decision(
        session_id=session_id,
        payload=payload,
        principal=principal,
        runtime=runtime,
    )


@router.post(
    "/v1/agent-team/sessions/{session_id}/merge",
    response_model=AgentTeamMergeDecisionResponse,
    include_in_schema=False,
)
def apply_agent_team_merge_decision_legacy(
    session_id: str,
    payload: ApplyAgentTeamMergeDecisionRequest,
    response: Response,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamMergeDecisionResponse:
    _mark_deprecated_route(
        response,
        canonical_path=f"/v1/agent-team/sessions/{session_id}/merge-decision",
    )
    return _apply_agent_team_merge_decision(
        session_id=session_id,
        payload=payload,
        principal=principal,
        runtime=runtime,
    )


def _apply_agent_team_merge_decision(
    *,
    session_id: str,
    payload: ApplyAgentTeamMergeDecisionRequest,
    principal: Principal,
    runtime: AppRuntime,
) -> AgentTeamMergeDecisionResponse:
    service = _agent_team_service_or_503(runtime)
    try:
        decision = service.apply_merge_decision(
            session_id=session_id,
            user_id=principal.user_id,
            approved=payload.apply if payload.apply is not None else payload.approved,
            action=payload.next_action or payload.action,
            rationale=payload.rationale,
            accepted_tasks=payload.accepted_tasks,
            rejected_tasks=payload.rejected_tasks,
        )
    except Exception as exc:  # noqa: BLE001
        raise _agent_team_error(exc) from exc
    session = service.get_session(session_id, user_id=principal.user_id)
    merge_bundle = None
    if session.latest_merge_bundle:
        from focus_agent.core.agent_team import AgentTeamMergeBundle

        merge_bundle = AgentTeamMergeBundle.model_validate(session.latest_merge_bundle)
    return AgentTeamMergeDecisionResponse(
        decision=decision,
        session=session,
        merge_bundle=merge_bundle,
        applied=decision.approved,
    )


@router.post(
    "/v1/agent-team/sessions/{session_id}/merge-review",
    response_model=AgentTeamMergeReviewResponse,
)
def create_agent_team_merge_review(
    session_id: str,
    payload: CreateAgentTeamMergeReviewRequest | None = None,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamMergeReviewResponse:
    service = _agent_team_service_or_503(runtime)
    request = payload or CreateAgentTeamMergeReviewRequest()
    try:
        review = service.create_merge_review(
            session_id=session_id,
            user_id=principal.user_id,
            selected_task_ids=request.selected_task_ids,
            excluded_task_ids=request.excluded_task_ids,
            title=request.title,
            metadata=request.metadata,
        )
        events = service.list_merge_review_events(
            session_id=session_id,
            review_id=review.review_id,
            user_id=principal.user_id,
        )
    except Exception as exc:  # noqa: BLE001
        raise _agent_team_error(exc) from exc
    return AgentTeamMergeReviewResponse(review=review, events=events)


@router.get(
    "/v1/agent-team/sessions/{session_id}/merge-review",
    response_model=AgentTeamMergeReviewListResponse,
)
def list_agent_team_merge_reviews(
    session_id: str,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamMergeReviewListResponse:
    service = _agent_team_service_or_503(runtime)
    try:
        reviews = service.list_merge_reviews(session_id=session_id, user_id=principal.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _agent_team_error(exc) from exc
    return AgentTeamMergeReviewListResponse(
        reviews=reviews,
        items=reviews,
        count=len(reviews),
        latest=reviews[0] if reviews else None,
    )


@router.patch(
    "/v1/agent-team/sessions/{session_id}/merge-review/{review_id}",
    response_model=AgentTeamMergeReviewResponse,
)
def update_agent_team_merge_review(
    session_id: str,
    review_id: str,
    payload: UpdateAgentTeamMergeReviewRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamMergeReviewResponse:
    service = _agent_team_service_or_503(runtime)
    try:
        review = service.update_merge_review(
            session_id=session_id,
            review_id=review_id,
            user_id=principal.user_id,
            selected_task_ids=payload.selected_task_ids,
            excluded_task_ids=payload.excluded_task_ids,
            status=payload.status,
            title=payload.title,
            metadata=payload.metadata,
        )
        events = service.list_merge_review_events(
            session_id=session_id,
            review_id=review_id,
            user_id=principal.user_id,
        )
    except Exception as exc:  # noqa: BLE001
        raise _agent_team_error(exc) from exc
    return AgentTeamMergeReviewResponse(review=review, events=events)


@router.post(
    "/v1/agent-team/sessions/{session_id}/merge-review/{review_id}/preview",
    response_model=AgentTeamMergeReviewResponse,
)
def preview_agent_team_merge_review(
    session_id: str,
    review_id: str,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamMergeReviewResponse:
    service = _agent_team_service_or_503(runtime)
    try:
        review = service.preview_merge_review(
            session_id=session_id,
            review_id=review_id,
            user_id=principal.user_id,
        )
        events = service.list_merge_review_events(
            session_id=session_id,
            review_id=review_id,
            user_id=principal.user_id,
        )
    except Exception as exc:  # noqa: BLE001
        raise _agent_team_error(exc) from exc
    return AgentTeamMergeReviewResponse(review=review, events=events)


@router.post(
    "/v1/agent-team/sessions/{session_id}/merge-review/{review_id}/apply",
    response_model=AgentTeamMergeReviewResponse,
)
def apply_agent_team_merge_review(
    session_id: str,
    review_id: str,
    payload: ApplyAgentTeamMergeReviewRequest | None = None,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamMergeReviewResponse:
    service = _agent_team_service_or_503(runtime)
    request = payload or ApplyAgentTeamMergeReviewRequest()
    try:
        review = service.apply_merge_review(
            session_id=session_id,
            review_id=review_id,
            user_id=principal.user_id,
            apply_target_path=request.apply_target_path,
        )
        events = service.list_merge_review_events(
            session_id=session_id,
            review_id=review_id,
            user_id=principal.user_id,
        )
    except Exception as exc:  # noqa: BLE001
        raise _agent_team_error(exc) from exc
    return AgentTeamMergeReviewResponse(review=review, events=events)


@router.post(
    "/v1/agent-team/sessions/{session_id}/merge-review/{review_id}/reject",
    response_model=AgentTeamMergeReviewResponse,
)
def reject_agent_team_merge_review(
    session_id: str,
    review_id: str,
    payload: RejectAgentTeamMergeReviewRequest | None = None,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamMergeReviewResponse:
    service = _agent_team_service_or_503(runtime)
    request = payload or RejectAgentTeamMergeReviewRequest()
    try:
        review = service.reject_merge_review(
            session_id=session_id,
            review_id=review_id,
            user_id=principal.user_id,
            rationale=request.rationale,
        )
        events = service.list_merge_review_events(
            session_id=session_id,
            review_id=review_id,
            user_id=principal.user_id,
        )
    except Exception as exc:  # noqa: BLE001
        raise _agent_team_error(exc) from exc
    return AgentTeamMergeReviewResponse(review=review, events=events)


@router.post(
    "/v1/agent-team/sessions/{session_id}/merge-review/{review_id}/capture",
    response_model=AgentTeamMergeReviewCaptureResponse,
)
def capture_agent_team_merge_review(
    session_id: str,
    review_id: str,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamMergeReviewCaptureResponse:
    service = _agent_team_service_or_503(runtime)
    try:
        capture = service.capture_merge_review(
            session_id=session_id,
            review_id=review_id,
            user_id=principal.user_id,
        )
    except Exception as exc:  # noqa: BLE001
        raise _agent_team_error(exc) from exc
    return AgentTeamMergeReviewCaptureResponse(capture=capture)


def _agent_team_approval_queue(service: object):
    coordination_backend = getattr(service, "coordination_backend", None)
    approval_queue = getattr(coordination_backend, "approval_queue", None)
    if approval_queue is None:
        raise RuntimeError("Agent Team tool approval queue is unavailable.")
    return approval_queue


def _pending_tool_approvals_for_session(
    service: object,
    session: object,
) -> list[AgentTeamToolApprovalContract]:
    approval_queue = _agent_team_approval_queue(service)
    if not hasattr(approval_queue, "list_pending"):
        return []
    session_ids = {
        str(getattr(session, "session_id", "")),
        str(getattr(session, "root_thread_id", "")),
    }
    approvals = []
    for request in approval_queue.list_pending():
        if str(getattr(request, "session_id", "")) in session_ids:
            approvals.append(
                AgentTeamToolApprovalContract.model_validate(_tool_approval_payload(request))
            )
    return approvals


def _get_tool_approval_request(approval_queue: object, request_id: str):
    get = getattr(approval_queue, "get", None)
    if callable(get):
        return get(request_id)
    if not hasattr(approval_queue, "list_pending"):
        return None
    for request in approval_queue.list_pending():
        if str(getattr(request, "request_id", "")) == request_id:
            return request
    return None


def _tool_approval_payload(request: object) -> dict[str, object]:
    status = getattr(request, "status", "pending")
    status_value = getattr(status, "value", status)
    return {
        "request_id": str(getattr(request, "request_id", "")),
        "session_id": str(getattr(request, "session_id", "")),
        "agent_id": str(getattr(request, "agent_id", "")),
        "tool_name": str(getattr(request, "tool_name", "")),
        "tool_args": dict(getattr(request, "tool_args", {}) or {}),
        "risk_level": str(getattr(request, "risk_level", "low") or "low"),
        "status": str(status_value or "pending"),
        "submitted_at": float(getattr(request, "submitted_at", 0.0) or 0.0),
        "timeout_at": float(getattr(request, "timeout_at", 0.0) or 0.0),
        "decided_by": getattr(request, "decided_by", None),
    }


__all__ = [
    "_DEPRECATED_ROUTE_LINK_REL",
    "_call_plan_session",
    "_mark_deprecated_route",
    "_model_payload",
    "_planning_metadata_payload",
    "_view_response",
    "router",
]
