from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status

from focus_agent.engine.runtime import AppRuntime
from focus_agent.model_registry import build_model_catalog
from focus_agent.security.permissions import is_admin_role, permissions_for_roles
from focus_agent.security.tokens import Principal, create_access_token
from focus_agent.services.auth import (
    AccountLockedError,
    AuthService,
    AuthServiceError,
    AuthTokenPair,
    InvalidCredentialsError,
    PasswordMismatchError,
    SessionRevokedError,
    UsernameTakenError,
    WeakPasswordError,
)
from focus_agent.services.users import UserInactiveError

from ..contracts import (
    AuthChangePasswordRequest,
    AuthLoginRequest,
    AuthLogoutRequest,
    AuthRefreshRequest,
    AuthRegisterRequest,
    AuthTokenResponse,
    DemoTokenRequest,
    ModelCatalogResponse,
    PrincipalResponse,
    TokenResponse,
    UserResponse,
    UserSessionListResponse,
    UserSessionResponse,
)
from ..deps import (
    allow_implicit_admin_bootstrap,
    get_app_runtime,
    get_auth_service,
    get_current_principal,
)

router = APIRouter()


@router.post("/v1/auth/demo-token", response_model=TokenResponse)
def issue_demo_token(
    payload: DemoTokenRequest, runtime: AppRuntime = Depends(get_app_runtime)
) -> TokenResponse:
    if not runtime.settings.auth_demo_tokens_enabled:
        raise HTTPException(status_code=404, detail="Demo token issuance is disabled.")
    user_service = getattr(runtime, "user_service", None)
    if user_service is not None:
        try:
            user_service.ensure_user_from_principal(
                Principal(user_id=payload.user_id, tenant_id=payload.tenant_id),
                allow_admin_bootstrap=allow_implicit_admin_bootstrap(runtime.settings),
                bootstrap_admin_user_ids=runtime.settings.auth_bootstrap_admin_user_ids,
            )
        except UserInactiveError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
    token = create_access_token(
        settings=runtime.settings,
        user_id=payload.user_id,
        tenant_id=payload.tenant_id,
        scopes=payload.scopes,
    )
    return TokenResponse(
        access_token=token,
        expires_in_seconds=runtime.settings.auth_access_token_ttl_seconds,
        issuer=runtime.settings.auth_jwt_issuer,
    )


@router.post(
    "/v1/auth/register", response_model=AuthTokenResponse, status_code=status.HTTP_201_CREATED
)
def register(
    payload: AuthRegisterRequest,
    request: Request,
    response: Response,
    runtime: AppRuntime = Depends(get_app_runtime),
    service: AuthService = Depends(get_auth_service),
) -> AuthTokenResponse:
    try:
        token_pair = service.register(
            username=payload.username,
            password=payload.password,
            display_name=payload.display_name,
            user_agent=request.headers.get("user-agent"),
            ip_address=_client_ip(request),
        )
    except (UsernameTakenError, WeakPasswordError) as exc:
        raise _auth_exception(
            exc,
            status.HTTP_409_CONFLICT
            if isinstance(exc, UsernameTakenError)
            else status.HTTP_400_BAD_REQUEST,
        ) from exc
    _set_auth_cookies(response, token_pair, runtime=runtime)
    return _token_response(token_pair)


@router.post("/v1/auth/login", response_model=AuthTokenResponse)
def login(
    payload: AuthLoginRequest,
    request: Request,
    response: Response,
    runtime: AppRuntime = Depends(get_app_runtime),
    service: AuthService = Depends(get_auth_service),
) -> AuthTokenResponse:
    try:
        token_pair = service.login(
            username=payload.username,
            password=payload.password,
            user_agent=request.headers.get("user-agent"),
            ip_address=_client_ip(request),
        )
    except InvalidCredentialsError as exc:
        raise _auth_exception(exc, status.HTTP_401_UNAUTHORIZED) from exc
    except AccountLockedError as exc:
        raise _auth_exception(exc, status.HTTP_403_FORBIDDEN) from exc
    _set_auth_cookies(response, token_pair, runtime=runtime)
    return _token_response(token_pair)


@router.post("/v1/auth/refresh", response_model=AuthTokenResponse)
def refresh(
    request: Request,
    response: Response,
    payload: AuthRefreshRequest = Body(default_factory=AuthRefreshRequest),
    runtime: AppRuntime = Depends(get_app_runtime),
    service: AuthService = Depends(get_auth_service),
) -> AuthTokenResponse:
    refresh_token = payload.refresh_token or request.cookies.get(
        runtime.settings.auth_refresh_cookie_name
    )
    try:
        token_pair = service.refresh(refresh_token or "")
    except SessionRevokedError as exc:
        raise _auth_exception(exc, status.HTTP_401_UNAUTHORIZED) from exc
    _set_auth_cookies(response, token_pair, runtime=runtime)
    return _token_response(token_pair)


@router.post("/v1/auth/logout")
def logout(
    request: Request,
    response: Response,
    payload: AuthLogoutRequest = Body(default_factory=AuthLogoutRequest),
    runtime: AppRuntime = Depends(get_app_runtime),
    service: AuthService = Depends(get_auth_service),
) -> dict[str, bool]:
    refresh_token = payload.refresh_token or request.cookies.get(
        runtime.settings.auth_refresh_cookie_name
    )
    service.logout(refresh_token)
    _clear_auth_cookies(response, runtime=runtime)
    return {"ok": True}


@router.post("/v1/auth/change-password", response_model=UserResponse)
def change_password(
    payload: AuthChangePasswordRequest,
    request: Request,
    runtime: AppRuntime = Depends(get_app_runtime),
    service: AuthService = Depends(get_auth_service),
    principal: Principal = Depends(get_current_principal),
) -> UserResponse:
    try:
        user = service.change_password(
            user_id=principal.user_id,
            current_password=payload.current_password,
            new_password=payload.new_password,
            refresh_token=request.cookies.get(runtime.settings.auth_refresh_cookie_name),
        )
    except PasswordMismatchError as exc:
        raise _auth_exception(exc, status.HTTP_400_BAD_REQUEST) from exc
    except WeakPasswordError as exc:
        raise _auth_exception(exc, status.HTTP_400_BAD_REQUEST) from exc
    return UserResponse.from_user(user)


@router.get("/v1/auth/sessions", response_model=UserSessionListResponse)
def list_my_sessions(
    request: Request,
    runtime: AppRuntime = Depends(get_app_runtime),
    service: AuthService = Depends(get_auth_service),
    principal: Principal = Depends(get_current_principal),
) -> UserSessionListResponse:
    current_session_id = _refresh_session_id(
        request.cookies.get(runtime.settings.auth_refresh_cookie_name)
    )
    sessions = service.repository.list_sessions(user_id=principal.user_id, include_revoked=True)
    return UserSessionListResponse(
        items=[
            UserSessionResponse.from_session(session, current_session_id=current_session_id)
            for session in sessions
        ],
        count=len(sessions),
    )


@router.post("/v1/auth/sessions/{session_id}/revoke", response_model=UserSessionResponse)
def revoke_my_session(
    session_id: str,
    service: AuthService = Depends(get_auth_service),
    principal: Principal = Depends(get_current_principal),
) -> UserSessionResponse:
    try:
        session = service.repository.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown user session."
        ) from exc
    if session.user_id != principal.user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown user session.")
    revoked = service.repository.revoke_session(session_id, revoked_at=_now())
    return UserSessionResponse.from_session(revoked)


@router.get("/v1/auth/me", response_model=PrincipalResponse)
def get_me(
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> PrincipalResponse:
    user_response: UserResponse | None = None
    roles: list[str] = []
    permissions: list[str] = []
    is_admin = False
    user_service = getattr(runtime, "user_service", None)
    if user_service is not None:
        try:
            user = user_service.ensure_user_from_principal(
                principal,
                allow_admin_bootstrap=allow_implicit_admin_bootstrap(runtime.settings),
                bootstrap_admin_user_ids=runtime.settings.auth_bootstrap_admin_user_ids,
            )
        except UserInactiveError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        user_response = UserResponse.from_user(user)
        roles = list(user.roles)
        permissions = list(permissions_for_roles(user.roles))
        is_admin = is_admin_role(user.roles)
    return PrincipalResponse(
        user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        scopes=list(principal.scopes),
        auth_enabled=runtime.settings.auth_enabled,
        user=user_response,
        roles=roles,
        permissions=permissions,
        is_admin=is_admin,
    )


@router.get("/v1/models", response_model=ModelCatalogResponse)
def list_models(
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> ModelCatalogResponse:
    del principal
    return ModelCatalogResponse(
        default_model=runtime.settings.model,
        models=[
            {
                "id": item.id,
                "provider": item.provider,
                "provider_label": item.provider_label,
                "provider_logo_slug": item.provider_logo_slug,
                "provider_logo_letter": item.provider_logo_letter,
                "name": item.name,
                "label": item.label,
                "is_default": item.is_default,
                "supports_thinking": item.supports_thinking,
                "default_thinking_enabled": item.default_thinking_enabled,
            }
            for item in build_model_catalog(runtime.settings)
        ],
    )


def _token_response(token_pair: AuthTokenPair) -> AuthTokenResponse:
    return AuthTokenResponse(
        access_token=token_pair.access_token,
        refresh_token=token_pair.refresh_token,
        expires_in_seconds=token_pair.expires_in_seconds,
        issuer=token_pair.issuer,
        user=UserResponse.from_user(token_pair.user),
    )


def _set_auth_cookies(
    response: Response,
    token_pair: AuthTokenPair,
    *,
    runtime: AppRuntime,
) -> None:
    response.set_cookie(
        runtime.settings.auth_access_cookie_name,
        token_pair.access_token,
        httponly=True,
        secure=runtime.settings.auth_cookie_secure,
        samesite=runtime.settings.auth_cookie_samesite,
        max_age=token_pair.expires_in_seconds,
        path="/",
    )
    response.set_cookie(
        runtime.settings.auth_refresh_cookie_name,
        token_pair.refresh_token,
        httponly=True,
        secure=runtime.settings.auth_cookie_secure,
        samesite=runtime.settings.auth_cookie_samesite,
        max_age=runtime.settings.auth_refresh_token_ttl_seconds,
        path="/",
    )


def _clear_auth_cookies(response: Response, *, runtime: AppRuntime) -> None:
    response.delete_cookie(runtime.settings.auth_access_cookie_name, path="/")
    response.delete_cookie(runtime.settings.auth_refresh_cookie_name, path="/")


def _auth_exception(exc: AuthServiceError, status_code: int) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": exc.code, "message": str(exc)},
    )


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client is not None else None


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _refresh_session_id(refresh_token: str | None) -> str | None:
    if not refresh_token:
        return None
    return hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()
