from __future__ import annotations

# ruff: noqa: F403, F405
from ..route_helpers import *

router = APIRouter()


@router.post('/v1/agent-team/sessions', response_model=AgentTeamSessionResponse)
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

@router.get('/v1/agent-team/sessions', response_model=AgentTeamSessionListResponse)
def list_agent_team_sessions(
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamSessionListResponse:
    service = _agent_team_service_or_503(runtime)
    sessions = service.list_sessions(user_id=principal.user_id)
    return AgentTeamSessionListResponse(sessions=sessions, items=sessions, count=len(sessions))

@router.get('/v1/agent-team/sessions/{session_id}', response_model=AgentTeamSessionResponse)
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

@router.post('/v1/agent-team/sessions/{session_id}/dispatch', response_model=AgentTeamDispatchResponse)
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
            create_branches=request.auto_fork_branch if request.auto_fork_branch is not None else request.create_branches,
            parent_thread_id=request.parent_thread_id,
        )
    except Exception as exc:  # noqa: BLE001
        raise _agent_team_error(exc) from exc
    return AgentTeamDispatchResponse(session=session, tasks=tasks, items=tasks, count=len(tasks))

@router.post('/v1/agent-team/sessions/{session_id}/tasks', response_model=AgentTeamTaskResponse)
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
            scope=payload.scope,
            dependencies=payload.dependencies,
            create_branch=payload.auto_fork_branch if payload.auto_fork_branch is not None else payload.create_branch,
            branch_name=payload.branch_name,
            parent_thread_id=payload.parent_thread_id,
        )
    except Exception as exc:  # noqa: BLE001
        raise _agent_team_error(exc) from exc
    return AgentTeamTaskResponse(task=task)

@router.get('/v1/agent-team/sessions/{session_id}/tasks', response_model=AgentTeamTaskListResponse)
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

@router.get('/v1/agent-team/tasks/{task_id}', response_model=AgentTeamTaskResponse)
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

@router.patch('/v1/agent-team/tasks/{task_id}', response_model=AgentTeamTaskResponse)
@router.post('/v1/agent-team/tasks/{task_id}/status', response_model=AgentTeamTaskResponse)
def update_agent_team_task_status(
    task_id: str,
    payload: UpdateAgentTeamTaskRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamTaskResponse:
    service = _agent_team_service_or_503(runtime)
    try:
        task = service.update_task(
            task_id=task_id,
            user_id=principal.user_id,
            status=payload.status,
            changed_files=payload.changed_files,
            verification_summary=payload.verification_summary,
            risk_notes=payload.risk_notes,
        )
    except Exception as exc:  # noqa: BLE001
        raise _agent_team_error(exc) from exc
    return AgentTeamTaskResponse(task=task)

@router.post('/v1/agent-team/tasks/{task_id}/outputs', response_model=AgentTeamTaskOutputResponse)
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
            test_evidence=[*payload.test_evidence, *([payload.verification_summary] if payload.verification_summary else [])],
            risk_notes=payload.risk_notes,
            metadata=payload.metadata,
        )
    except Exception as exc:  # noqa: BLE001
        raise _agent_team_error(exc) from exc
    task = service.get_task(task_id, user_id=principal.user_id)
    return AgentTeamTaskOutputResponse(output=output, task=task)

@router.post('/v1/agent-team/sessions/{session_id}/merge-bundle', response_model=AgentTeamMergeBundleResponse)
@router.post('/v1/agent-team/sessions/{session_id}/merge-proposal', response_model=AgentTeamMergeBundleResponse)
def prepare_agent_team_merge_bundle(
    session_id: str,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamMergeBundleResponse:
    service = _agent_team_service_or_503(runtime)
    try:
        bundle = service.prepare_merge_bundle(session_id=session_id, user_id=principal.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _agent_team_error(exc) from exc
    return AgentTeamMergeBundleResponse(bundle=bundle)

@router.post('/v1/agent-team/sessions/{session_id}/merge-decision', response_model=AgentTeamMergeDecisionResponse)
@router.post('/v1/agent-team/sessions/{session_id}/merge', response_model=AgentTeamMergeDecisionResponse)
def apply_agent_team_merge_decision(
    session_id: str,
    payload: ApplyAgentTeamMergeDecisionRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
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
