from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel

from focus_agent.engine.runtime import AppRuntime
from focus_agent.security.tokens import Principal

from ..contract_models.agent_team import (
    AgentTeamEvidenceListResponse,
    AgentTeamReadinessResponse,
    AgentTeamRevisionCommandRequest,
    AgentTeamRevisionCommandResponse,
    AgentTeamTaskRunListResponse,
    AgentTeamTaskRunResponse,
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
from ..route_utils.agent_team import (
    _agent_team_service_or_503,
    agent_team_errors,
    agent_team_v2_errors,
    agent_team_v2_method_or_501,
    agent_team_v2_readiness,
)
from ..route_utils.agent_team_responses import (
    _mark_deprecated_route,
    _planning_metadata_payload,
    _view_response,
)
from . import agent_team_merge_reviews, agent_team_tool_approvals

router = APIRouter()


@router.get("/v2/agent-team/readiness", response_model=AgentTeamReadinessResponse)
def get_agent_team_v2_readiness(
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamReadinessResponse:
    service = _agent_team_service_or_503(runtime)
    return agent_team_v2_readiness(runtime, service)


@router.get(
    "/v2/agent-team/task-runs/{task_run_id}",
    response_model=AgentTeamTaskRunResponse,
)
def get_agent_team_task_run_v2(
    task_run_id: str,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamTaskRunResponse:
    service = _agent_team_service_or_503(runtime)
    get_task_run = agent_team_v2_method_or_501(service, "get_task_run")
    with agent_team_v2_errors("get_task_run"):
        task_run = get_task_run(task_run_id=task_run_id, user_id=principal.user_id)
    return AgentTeamTaskRunResponse(task_run=task_run)


@router.get(
    "/v2/agent-team/tasks/{task_id}/runs",
    response_model=AgentTeamTaskRunListResponse,
)
def list_agent_team_task_runs_v2(
    task_id: str,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamTaskRunListResponse:
    service = _agent_team_service_or_503(runtime)
    list_task_runs = agent_team_v2_method_or_501(service, "list_task_runs")
    with agent_team_v2_errors("list_task_runs"):
        task_runs = list_task_runs(task_id=task_id, user_id=principal.user_id)
    return AgentTeamTaskRunListResponse(items=task_runs, count=len(task_runs))


@router.get(
    "/v2/agent-team/sessions/{session_id}/evidence",
    response_model=AgentTeamEvidenceListResponse,
)
def list_agent_team_session_evidence_v2(
    session_id: str,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamEvidenceListResponse:
    service = _agent_team_service_or_503(runtime)
    list_evidence_records = agent_team_v2_method_or_501(service, "list_evidence_records")
    with agent_team_v2_errors("list_evidence_records"):
        evidence = list_evidence_records(session_id=session_id, user_id=principal.user_id)
    return AgentTeamEvidenceListResponse(items=evidence, count=len(evidence))


@router.post(
    "/v2/agent-team/sessions/{session_id}/revisions/commands",
    response_model=AgentTeamRevisionCommandResponse,
)
def execute_agent_team_revision_command_v2(
    session_id: str,
    payload: AgentTeamRevisionCommandRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamRevisionCommandResponse:
    service = _agent_team_service_or_503(runtime)
    execute_revision_command = agent_team_v2_method_or_501(
        service,
        "execute_revision_command",
    )
    with agent_team_v2_errors(
        "execute_revision_command",
        (RuntimeError, status.HTTP_409_CONFLICT),
    ):
        outcome = execute_revision_command(
            session_id=session_id,
            user_id=principal.user_id,
            command=payload.command,
            revision_id=payload.revision_id,
            parent_revision_id=payload.parent_revision_id,
            task_ids=payload.task_ids,
            metadata=payload.metadata,
        )
    return AgentTeamRevisionCommandResponse(
        command=payload.command,
        session_id=session_id,
        outcome=outcome,
    )


@router.post("/v1/agent-team/sessions", response_model=AgentTeamSessionResponse)
def create_agent_team_session(
    payload: CreateAgentTeamSessionRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamSessionResponse:
    service = _agent_team_service_or_503(runtime)
    with agent_team_errors():
        session = service.create_session(
            root_thread_id=payload.root_thread_id,
            user_id=principal.user_id,
            title=payload.title,
            goal=payload.goal,
        )
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
    with agent_team_errors():
        sessions = service.list_sessions(
            user_id=principal.user_id,
            root_thread_id=root_thread_id,
            status=status,
            limit=limit,
            offset=offset,
        )
    return AgentTeamSessionListResponse(sessions=sessions, items=sessions, count=len(sessions))


@router.get("/v1/agent-team/sessions/{session_id}", response_model=AgentTeamSessionResponse)
def get_agent_team_session(
    session_id: str,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamSessionResponse:
    service = _agent_team_service_or_503(runtime)
    with agent_team_errors():
        session = service.get_session(session_id, user_id=principal.user_id)
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
    with agent_team_errors():
        session, tasks = service.dispatch_default_tasks(
            session_id=session_id,
            user_id=principal.user_id,
            create_branches=request.auto_fork_branch
            if request.auto_fork_branch is not None
            else request.create_branches,
            parent_thread_id=request.parent_thread_id,
        )
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
    with agent_team_errors():
        session, tasks = service.plan_session(
            session_id=session_id,
            user_id=principal.user_id,
            create_branches=create_branches,
            parent_thread_id=request.parent_thread_id,
            replace_existing=bool(request.replace_existing),
            granularity=request.granularity,
            focus=request.focus,
            max_tasks=request.max_tasks,
        )
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
    with agent_team_errors():
        service.run_ready_tasks(
            session_id=session_id,
            user_id=principal.user_id,
            task_ids=payload.task_ids if payload else None,
        )
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
    with agent_team_errors():
        return _view_response(
            service.get_session_view(session_id=session_id, user_id=principal.user_id)
        )


@router.post("/v1/agent-team/sessions/{session_id}/tasks", response_model=AgentTeamTaskResponse)
def create_agent_team_task(
    session_id: str,
    payload: CreateAgentTeamTaskRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamTaskResponse:
    service = _agent_team_service_or_503(runtime)
    with agent_team_errors():
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
    return AgentTeamTaskResponse(task=task)


@router.get("/v1/agent-team/sessions/{session_id}/tasks", response_model=AgentTeamTaskListResponse)
def list_agent_team_tasks(
    session_id: str,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamTaskListResponse:
    service = _agent_team_service_or_503(runtime)
    with agent_team_errors():
        tasks = service.list_tasks(session_id=session_id, user_id=principal.user_id)
    return AgentTeamTaskListResponse(tasks=tasks, items=tasks, count=len(tasks))


@router.get("/v1/agent-team/tasks/{task_id}", response_model=AgentTeamTaskResponse)
def get_agent_team_task(
    task_id: str,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamTaskResponse:
    service = _agent_team_service_or_503(runtime)
    with agent_team_errors():
        task = service.get_task(task_id, user_id=principal.user_id)
    return AgentTeamTaskResponse(task=task)


@router.patch("/v1/agent-team/tasks/{task_id}", response_model=AgentTeamTaskResponse)
def update_agent_team_task_status(
    task_id: str,
    payload: UpdateAgentTeamTaskRequest,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamTaskResponse:
    service = _agent_team_service_or_503(runtime)
    with agent_team_errors():
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
    return AgentTeamTaskResponse(task=task)


@router.post("/v1/agent-team/tasks/{task_id}/run", response_model=AgentTeamTaskResponse)
def run_agent_team_task(
    task_id: str,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamTaskResponse:
    service = _agent_team_service_or_503(runtime)
    with agent_team_errors():
        task = service.run_task(task_id=task_id, user_id=principal.user_id)
    return AgentTeamTaskResponse(task=task)


@router.post("/v1/agent-team/tasks/{task_id}/retry", response_model=AgentTeamTaskResponse)
def retry_agent_team_task(
    task_id: str,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamTaskResponse:
    service = _agent_team_service_or_503(runtime)
    with agent_team_errors():
        task = service.retry_task(task_id=task_id, user_id=principal.user_id)
    return AgentTeamTaskResponse(task=task)


@router.post("/v1/agent-team/tasks/{task_id}/cancel", response_model=AgentTeamTaskResponse)
def cancel_agent_team_task(
    task_id: str,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> AgentTeamTaskResponse:
    service = _agent_team_service_or_503(runtime)
    with agent_team_errors():
        task = service.cancel_task(task_id=task_id, user_id=principal.user_id)
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
    with agent_team_errors():
        service.cancel_session(session_id=session_id, user_id=principal.user_id)
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
    with agent_team_errors():
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
    service = _agent_team_service_or_503(runtime)
    with agent_team_errors():
        bundle = service.prepare_merge_bundle(session_id=session_id, user_id=principal.user_id)
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
    service = _agent_team_service_or_503(runtime)
    with agent_team_errors():
        decision = service.apply_merge_decision(
            session_id=session_id,
            user_id=principal.user_id,
            approved=payload.apply if payload.apply is not None else payload.approved,
            action=payload.next_action or payload.action,
            rationale=payload.rationale,
            accepted_tasks=payload.accepted_tasks,
            rejected_tasks=payload.rejected_tasks,
        )
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


def _deprecated_route_alias(
    path: str,
    endpoint: Callable[..., Any],
    *,
    canonical_path: str,
    response_model: type[BaseModel],
) -> None:
    """Register a hidden legacy path that serves ``endpoint`` and points at its successor."""

    def _mark(request: Request, response: Response) -> None:
        _mark_deprecated_route(
            response, canonical_path=canonical_path.format(**request.path_params)
        )

    router.add_api_route(
        path,
        endpoint,
        methods=["POST"],
        response_model=response_model,
        include_in_schema=False,
        dependencies=[Depends(_mark)],
        name=f"{endpoint.__name__}_legacy",
    )


_deprecated_route_alias(
    "/v1/agent-team/tasks/{task_id}/status",
    update_agent_team_task_status,
    canonical_path="/v1/agent-team/tasks/{task_id}",
    response_model=AgentTeamTaskResponse,
)
_deprecated_route_alias(
    "/v1/agent-team/sessions/{session_id}/merge-proposal",
    prepare_agent_team_merge_bundle,
    canonical_path="/v1/agent-team/sessions/{session_id}/merge-bundle",
    response_model=AgentTeamMergeBundleResponse,
)
_deprecated_route_alias(
    "/v1/agent-team/sessions/{session_id}/merge",
    apply_agent_team_merge_decision,
    canonical_path="/v1/agent-team/sessions/{session_id}/merge-decision",
    response_model=AgentTeamMergeDecisionResponse,
)

router.include_router(agent_team_merge_reviews.router)
router.include_router(agent_team_tool_approvals.router)


__all__ = ["router"]
