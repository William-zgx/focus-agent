from __future__ import annotations

from fastapi import APIRouter, Depends

from focus_agent.engine.runtime import AppRuntime
from focus_agent.security.tokens import Principal

from ..contract_models.agent_team import (
    AgentTeamMergeReviewCaptureResponse,
    AgentTeamMergeReviewListResponse,
    AgentTeamMergeReviewResponse,
    ApplyAgentTeamMergeReviewRequest,
    CreateAgentTeamMergeReviewRequest,
    RejectAgentTeamMergeReviewRequest,
    UpdateAgentTeamMergeReviewRequest,
)
from ..deps import get_app_runtime, get_current_principal
from ..route_utils.agent_team import _agent_team_service_or_503, agent_team_errors

router = APIRouter()


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
    with agent_team_errors():
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
    with agent_team_errors():
        reviews = service.list_merge_reviews(session_id=session_id, user_id=principal.user_id)
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
    with agent_team_errors():
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
    with agent_team_errors():
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
    with agent_team_errors():
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
    with agent_team_errors():
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
    with agent_team_errors():
        capture = service.capture_merge_review(
            session_id=session_id,
            review_id=review_id,
            user_id=principal.user_id,
        )
    return AgentTeamMergeReviewCaptureResponse(capture=capture)
