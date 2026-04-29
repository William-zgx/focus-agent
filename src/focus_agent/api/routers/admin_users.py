from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

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
    AuditEventListResponse,
    AuditEventResponse,
    AdminResetPasswordRequest,
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
from ..deps import get_auth_service, get_user_service, require_permission

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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown user: {user_id}") from exc
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


__all__ = ["router"]


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _require_reason(reason: str | None) -> None:
    if not reason or not reason.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Audit reason is required.",
        )
