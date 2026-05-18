from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from focus_agent.core.repo_call import safe_repo_call
from focus_agent.core.users import AuditDecision
from focus_agent.repositories.user_repository import AuditEventListFilters, UserListFilters
from focus_agent.security.permissions import AuthContext
from focus_agent.services.auth import AuthService, WeakPasswordError
from focus_agent.services.users import (
    LastAdminError,
    UserConflictError,
    UserNotFoundError,
    UserService,
)

from ..contracts import (
    AdminResetPasswordRequest,
    AuditEventListResponse,
    AuditEventResponse,
    BackgroundDeadLetterJobListResponse,
    BackgroundDeadLetterJobResponse,
    BackgroundDeadLetterReplayResponse,
    BackgroundJobSummaryResponse,
    CreateUserRequest,
    RevokeUserSessionRequest,
    UpdateUserRequest,
    UpdateUserRolesRequest,
    UpdateUserStatusRequest,
    UserListResponse,
    UserResponse,
    UserSessionListResponse,
    UserSessionResponse,
)
from ..deps import (
    get_app_runtime,
    get_auth_service,
    get_user_service,
    require_admin_user,
    require_permission,
)

router = APIRouter(prefix="/v1/admin", tags=["admin"])


@router.get("/users", response_model=UserListResponse)
def list_users(
    status_filter: str | None = Query(default=None, alias="status"),
    role: str | None = None,
    tenant_id: str | None = None,
    query: str | None = None,
    limit: int = Query(default=50, ge=0, le=200),
    offset: int = Query(default=0, ge=0),
    service: UserService = Depends(get_user_service),
    context: AuthContext = Depends(require_permission("users:read")),
) -> UserListResponse:
    del context
    result = service.list_users(
        filters=UserListFilters(
            status=status_filter,
            role=role,
            tenant_id=tenant_id,
            query=query,
        ),
        limit=limit,
        offset=offset,
    )
    return UserListResponse(
        items=[UserResponse.from_user(user) for user in result.items],
        count=result.count,
        limit=result.limit,
        offset=result.offset,
    )


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: CreateUserRequest,
    request: Request,
    service: UserService = Depends(get_user_service),
    context: AuthContext = Depends(require_permission("users:create")),
) -> UserResponse:
    try:
        user = service.create_user(
            user_id=payload.user_id,
            username=payload.username,
            display_name=payload.display_name,
            email=payload.email,
            tenant_id=payload.tenant_id,
            status=payload.status,
            roles=payload.roles,
            metadata=payload.metadata,
            actor=context,
            request_id=getattr(request.state, "request_id", None),
        )
    except UserConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return UserResponse.from_user(user)


@router.get("/users/{user_id}", response_model=UserResponse)
def get_user(
    user_id: str,
    service: UserService = Depends(get_user_service),
    context: AuthContext = Depends(require_permission("users:read")),
) -> UserResponse:
    del context
    try:
        return UserResponse.from_user(service.get_user(user_id))
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: str,
    payload: UpdateUserRequest,
    request: Request,
    service: UserService = Depends(get_user_service),
    context: AuthContext = Depends(require_permission("users:update")),
) -> UserResponse:
    try:
        user = service.update_user(
            user_id,
            updates=payload.model_dump(exclude_unset=True),
            actor=context,
            request_id=getattr(request.state, "request_id", None),
        )
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except UserConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return UserResponse.from_user(user)


@router.post("/users/{user_id}/status", response_model=UserResponse)
def update_user_status(
    user_id: str,
    payload: UpdateUserStatusRequest,
    request: Request,
    service: UserService = Depends(get_user_service),
    context: AuthContext = Depends(require_permission("users:status")),
) -> UserResponse:
    _require_reason(payload.reason)
    try:
        user = service.update_user_status(
            user_id,
            status=payload.status,
            actor=context,
            reason=payload.reason,
            request_id=getattr(request.state, "request_id", None),
        )
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LastAdminError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return UserResponse.from_user(user)


@router.put("/users/{user_id}/roles", response_model=UserResponse)
def update_user_roles(
    user_id: str,
    payload: UpdateUserRolesRequest,
    request: Request,
    service: UserService = Depends(get_user_service),
    context: AuthContext = Depends(require_permission("users:roles")),
) -> UserResponse:
    _require_reason(payload.reason)
    try:
        user = service.update_user_roles(
            user_id,
            roles=payload.roles,
            actor=context,
            reason=payload.reason,
            request_id=getattr(request.state, "request_id", None),
        )
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LastAdminError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return UserResponse.from_user(user)


@router.get("/users/{user_id}/sessions", response_model=UserSessionListResponse)
def list_user_sessions(
    user_id: str,
    include_revoked: bool = False,
    service: UserService = Depends(get_user_service),
    context: AuthContext = Depends(require_permission("users:read")),
) -> UserSessionListResponse:
    del context
    try:
        service.get_user(user_id)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    sessions = service.repository.list_sessions(user_id=user_id, include_revoked=include_revoked)
    return UserSessionListResponse(
        items=[UserSessionResponse.from_session(session) for session in sessions],
        count=len(sessions),
    )


@router.post("/users/{user_id}/sessions/revoke", response_model=UserSessionResponse)
def revoke_user_session(
    user_id: str,
    payload: RevokeUserSessionRequest,
    request: Request,
    service: UserService = Depends(get_user_service),
    context: AuthContext = Depends(require_permission("users:update")),
) -> UserSessionResponse:
    _require_reason(payload.reason)
    try:
        service.get_user(user_id)
        session = service.repository.get_session(payload.session_id)
    except (UserNotFoundError, KeyError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if session.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown user session.")
    revoked = service.repository.revoke_session(payload.session_id, revoked_at=_now())
    service.record_admin_action(
        actor=context,
        action="users.sessions.revoke",
        resource_id=user_id,
        decision=AuditDecision.SUCCESS,
        reason=payload.reason,
        metadata={"session_id": payload.session_id},
        request_id=getattr(request.state, "request_id", None),
    )
    return UserSessionResponse.from_session(revoked)


@router.post("/users/{user_id}/password", response_model=UserResponse)
def reset_user_password(
    user_id: str,
    payload: AdminResetPasswordRequest,
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
    user_service: UserService = Depends(get_user_service),
    context: AuthContext = Depends(require_permission("users:update")),
) -> UserResponse:
    _require_reason(payload.reason)
    try:
        user = auth_service.reset_password(user_id=user_id, new_password=payload.new_password)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown user: {user_id}"
        ) from exc
    except WeakPasswordError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    user_service.record_admin_action(
        actor=context,
        action="users.password.reset",
        resource_id=user_id,
        decision=AuditDecision.SUCCESS,
        reason=payload.reason,
        request_id=getattr(request.state, "request_id", None),
    )
    return UserResponse.from_user(user)


@router.get("/audit-events", response_model=AuditEventListResponse)
def list_audit_events(
    actor_user_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    decision: str | None = None,
    limit: int = Query(default=50, ge=0, le=200),
    offset: int = Query(default=0, ge=0),
    service: UserService = Depends(get_user_service),
    context: AuthContext = Depends(require_permission("audit:read")),
) -> AuditEventListResponse:
    del context
    result = service.list_audit_events(
        filters=AuditEventListFilters(
            actor_user_id=actor_user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            decision=decision,
        ),
        limit=limit,
        offset=offset,
    )
    return AuditEventListResponse(
        items=[AuditEventResponse.from_event(event) for event in result.items],
        count=result.count,
        limit=result.limit,
        offset=result.offset,
    )


@router.get("/background-jobs/summary", response_model=BackgroundJobSummaryResponse)
def background_jobs_summary(
    runtime: Any = Depends(get_app_runtime),
    context: AuthContext = Depends(require_admin_user),
) -> BackgroundJobSummaryResponse:
    del context
    metrics = _background_job_metrics(runtime)
    warnings = _background_job_warnings(runtime, metrics)
    return BackgroundJobSummaryResponse(
        generated_at=_now(),
        status="degraded" if warnings else "ok",
        ready=not warnings,
        metrics=metrics,
        warnings=warnings,
    )


@router.get(
    "/background-jobs/dead-letter",
    response_model=BackgroundDeadLetterJobListResponse,
)
def list_background_dead_letter_jobs(
    limit: int = Query(default=50, ge=0, le=200),
    offset: int = Query(default=0, ge=0),
    runtime: Any = Depends(get_app_runtime),
    context: AuthContext = Depends(require_admin_user),
) -> BackgroundDeadLetterJobListResponse:
    del context
    backend = _background_job_backend(runtime)
    result = safe_repo_call(
        backend,
        "list_dead_letter_jobs",
        limit=limit,
        offset=offset,
        default_missing={"items": [], "count": 0, "limit": limit, "offset": offset},
        default_error={"items": [], "count": 0, "limit": limit, "offset": offset},
    )
    payload = dict(result or {})
    return BackgroundDeadLetterJobListResponse(
        items=[
            BackgroundDeadLetterJobResponse.model_validate(item)
            for item in list(payload.get("items") or [])
            if isinstance(item, dict)
        ],
        count=int(payload.get("count") or 0),
        limit=int(payload.get("limit") or limit),
        offset=int(payload.get("offset") or offset),
    )


@router.post(
    "/background-jobs/dead-letter/{job_key:path}/replay",
    response_model=BackgroundDeadLetterReplayResponse,
)
def replay_background_dead_letter_job(
    job_key: str,
    runtime: Any = Depends(get_app_runtime),
    context: AuthContext = Depends(require_admin_user),
) -> BackgroundDeadLetterReplayResponse:
    del context
    backend = _background_job_backend(runtime)
    replayed = bool(
        safe_repo_call(
            backend,
            "replay_dead_letter_job",
            job_key,
            default_missing=False,
            default_error=False,
        )
    )
    if not replayed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dead-lettered background job not found.",
        )
    return BackgroundDeadLetterReplayResponse(
        job_key=job_key,
        replayed=True,
        status="pending",
    )


__all__ = ["router"]


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _require_reason(reason: str | None) -> None:
    if not reason or not reason.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Audit reason is required.",
        )


def _background_job_metrics(runtime: Any) -> dict[str, int]:
    metrics = {
        **_snapshot_metrics(getattr(runtime, "background_work", None), "job_backend_error"),
        **_snapshot_metrics(
            getattr(runtime, "durable_background_worker", None), "durable_worker_snapshot_error"
        ),
    }
    return {str(key): int(value) for key, value in metrics.items()}


def _snapshot_metrics(source: Any, error_key: str) -> dict[str, int]:
    snapshot = safe_repo_call(
        source,
        "snapshot",
        default_missing={},
        default_error={error_key: 1},
    )
    try:
        return dict(snapshot)
    except Exception:  # noqa: BLE001
        return {error_key: 1}


def _background_job_warnings(runtime: Any, metrics: dict[str, int]) -> list[str]:
    warnings: list[str] = []
    for key in ("job_backend_error", "durable_worker_snapshot_error"):
        if int(metrics.get(key) or 0) > 0:
            warnings.append(key)
    dead_lettered = int(metrics.get("job_dead_lettered_total") or 0)
    if dead_lettered > 0:
        warnings.append(f"dead_lettered={dead_lettered}")
    threshold = max(
        int(
            float(
                getattr(
                    getattr(runtime, "settings", None), "background_job_old_pending_seconds", 900.0
                )
                or 0.0
            )
        ),
        0,
    )
    oldest_pending_seconds = int(metrics.get("job_oldest_pending_seconds") or 0)
    if threshold > 0 and oldest_pending_seconds > threshold:
        warnings.append(f"oldest_pending_seconds={oldest_pending_seconds}")
    return warnings


def _background_job_backend(runtime: Any) -> Any:
    worker = getattr(runtime, "durable_background_worker", None)
    backend = getattr(worker, "_job_backend", None)
    if backend is not None:
        return backend
    coordination_backend = getattr(runtime, "coordination_backend", None)
    backend = getattr(coordination_backend, "job_deduper", None)
    if backend is not None:
        return backend
    return getattr(runtime, "background_work", None)
