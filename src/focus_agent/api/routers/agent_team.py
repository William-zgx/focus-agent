from __future__ import annotations

from inspect import Parameter, signature
from typing import Any

from fastapi import APIRouter, Depends, Query, Response

from focus_agent.engine.runtime import AppRuntime
from focus_agent.security.tokens import Principal

from ..contracts import (
    AgentTeamDispatchResponse,
    AgentTeamMergeBundleResponse,
    AgentTeamMergeDecisionResponse,
    AgentTeamPlanSessionRequest,
    AgentTeamPlanningMetadata,
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

router = APIRouter()

_DEPRECATED_ROUTE_LINK_REL = "successor-version"


def _mark_deprecated_route(response: Response, *, canonical_path: str) -> None:
    response.headers["Deprecation"] = "true"
    response.headers["Link"] = f'<{canonical_path}>; rel="{_DEPRECATED_ROUTE_LINK_REL}"'
    response.headers["X-Focus-Agent-Canonical-Path"] = canonical_path


def _model_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    return {}


def _planning_metadata_payload(
    payload: dict[str, Any],
    *,
    default_source: str | None = None,
) -> dict[str, Any]:
    session = _model_payload(payload.get("session"))
    tasks = [_model_payload(task) for task in payload.get("tasks") or payload.get("items") or []]
    planning = payload.get("planning")
    if not isinstance(planning, dict):
        planning = session.get("planning") if isinstance(session.get("planning"), dict) else {}
    metadata: dict[str, Any] = {
        "source": planning.get("source") or session.get("planning_source") or default_source,
        "rationale": planning.get("rationale") or session.get("planning_rationale"),
        "planner_model_id": planning.get("planner_model_id") or session.get("planner_model_id"),
        "generated_at": planning.get("generated_at") or session.get("plan_generated_at"),
        "plan_hash": planning.get("plan_hash") or session.get("plan_hash"),
        "error": planning.get("error") or session.get("planning_error"),
        "task_count": planning.get("task_count") if planning.get("task_count") is not None else len(tasks),
    }
    for task in tasks:
        if metadata["source"] is None:
            metadata["source"] = task.get("plan_source")
        if metadata["rationale"] is None:
            metadata["rationale"] = task.get("planning_rationale")
        for ref in task.get("context_refs") or []:
            if not isinstance(ref, dict):
                continue
            if metadata["source"] is None:
                metadata["source"] = ref.get("plan_source") or ref.get("source")
            if metadata["rationale"] is None:
                metadata["rationale"] = ref.get("planning_rationale") or ref.get("rationale")
            if metadata["planner_model_id"] is None:
                metadata["planner_model_id"] = ref.get("planner_model_id") or ref.get("model_id")
            if metadata["generated_at"] is None:
                metadata["generated_at"] = ref.get("generated_at")
            if metadata["plan_hash"] is None:
                metadata["plan_hash"] = ref.get("plan_hash")
            if metadata["error"] is None:
                metadata["error"] = ref.get("error")
    return metadata


def _call_plan_session(service: Any, **kwargs: Any) -> tuple[Any, list[Any]]:
    plan_session = service.plan_session
    params = signature(plan_session).parameters
    if any(param.kind == Parameter.VAR_KEYWORD for param in params.values()):
        return plan_session(**kwargs)
    return plan_session(**{key: value for key, value in kwargs.items() if key in params})


def _view_response(payload: dict[str, Any]) -> AgentTeamSessionViewResponse:
    data = dict(payload)
    data["planning"] = _planning_metadata_payload(data)
    return AgentTeamSessionViewResponse.model_validate(data)


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

@router.post('/v1/agent-team/sessions/{session_id}/plan', response_model=AgentTeamDispatchResponse)
def plan_agent_team_session(
    session_id: str,
    payload: AgentTeamPlanSessionRequest | None = None,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamDispatchResponse:
    service = _agent_team_service_or_503(runtime)
    request = payload or AgentTeamPlanSessionRequest()
    create_branches = request.auto_fork_branch if request.auto_fork_branch is not None else request.create_branches
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

@router.post('/v1/agent-team/sessions/{session_id}/run', response_model=AgentTeamSessionViewResponse)
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
    return _view_response(service.get_session_view(session_id=session_id, user_id=principal.user_id))

@router.get('/v1/agent-team/sessions/{session_id}/view', response_model=AgentTeamSessionViewResponse)
def get_agent_team_session_view(
    session_id: str,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamSessionViewResponse:
    service = _agent_team_service_or_503(runtime)
    try:
        return _view_response(service.get_session_view(session_id=session_id, user_id=principal.user_id))
    except Exception as exc:  # noqa: BLE001
        raise _agent_team_error(exc) from exc

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
            acceptance_criteria=payload.acceptance_criteria,
            context_refs=payload.context_refs,
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
    '/v1/agent-team/tasks/{task_id}/status',
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
            verification_summary=payload.verification_summary,
            risk_notes=payload.risk_notes,
            acceptance_criteria=payload.acceptance_criteria,
            context_refs=payload.context_refs,
            dependencies=payload.dependencies,
            scope=payload.scope,
            run_status=payload.run_status,
            started_at=payload.started_at,
            finished_at=payload.finished_at,
            last_error=payload.last_error,
        )
    except Exception as exc:  # noqa: BLE001
        raise _agent_team_error(exc) from exc
    return AgentTeamTaskResponse(task=task)

@router.post('/v1/agent-team/tasks/{task_id}/run', response_model=AgentTeamTaskResponse)
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

@router.post('/v1/agent-team/tasks/{task_id}/retry', response_model=AgentTeamTaskResponse)
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

@router.post('/v1/agent-team/tasks/{task_id}/cancel', response_model=AgentTeamTaskResponse)
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

@router.post('/v1/agent-team/sessions/{session_id}/cancel', response_model=AgentTeamSessionViewResponse)
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
    return _view_response(service.get_session_view(session_id=session_id, user_id=principal.user_id))

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
    '/v1/agent-team/sessions/{session_id}/merge-proposal',
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

@router.post('/v1/agent-team/sessions/{session_id}/merge-decision', response_model=AgentTeamMergeDecisionResponse)
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
    '/v1/agent-team/sessions/{session_id}/merge',
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
