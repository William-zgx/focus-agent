from __future__ import annotations

from collections.abc import Callable, Iterable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from focus_agent.config import Settings
from focus_agent.core.users import User
from focus_agent.engine.runtime import AppRuntime, create_runtime
from focus_agent.security.permissions import AuthContext, is_admin_role, permissions_for_roles
from focus_agent.security.tokens import AuthError, Principal, decode_access_token
from focus_agent.services.auth import AuthService
from focus_agent.services.chat import ChatService, ChatServicePorts
from focus_agent.services.users import UserInactiveError, UserService

security = HTTPBearer(auto_error=False)
_BOOTSTRAP_DEVELOPMENT_ENVIRONMENTS = {"dev", "development", "local", "test", "testing", "ci"}
_DEFAULT_ACCESS_COOKIE_NAME = "focus_agent_access"


def _ensure_app_runtime(request: Request) -> AppRuntime:
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:
        runtime = create_runtime(Settings.from_env())
        request.app.state.runtime = runtime
    return runtime


def _ensure_chat_service(request: Request) -> ChatService:
    runtime = _ensure_app_runtime(request)
    chat_service = getattr(request.app.state, "chat_service", None)
    if chat_service is None:
        chat_service = ChatService(ChatServicePorts.from_runtime(runtime))
        request.app.state.chat_service = chat_service
        runtime.start_durable_background_worker(chat_service)
    return chat_service


def get_app_runtime(request: Request) -> AppRuntime:
    return _ensure_app_runtime(request)


def get_chat_service(request: Request) -> ChatService:
    return _ensure_chat_service(request)


def get_user_service(runtime: AppRuntime = Depends(get_app_runtime)) -> UserService:
    user_service = getattr(runtime, "user_service", None)
    if user_service is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="User service is not configured.",
        )
    return user_service


def get_auth_service(runtime: AppRuntime = Depends(get_app_runtime)) -> AuthService:
    auth_service = getattr(runtime, "auth_service", None)
    if auth_service is not None:
        return auth_service
    repository = getattr(runtime, "user_repository", None)
    if repository is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="User repository is not configured.",
        )
    auth_service = AuthService(repository, settings=runtime.settings)
    try:
        runtime.auth_service = auth_service
    except Exception:  # noqa: BLE001 - runtimes used in tests may be immutable namespaces.
        pass
    return auth_service


def allow_implicit_admin_bootstrap(settings: Settings) -> bool:
    if not settings.database_uri:
        return True
    return settings.app_environment.lower() in _BOOTSTRAP_DEVELOPMENT_ENVIRONMENTS


def _principal_from_credentials(
    credentials: HTTPAuthorizationCredentials | None,
    *,
    runtime: AppRuntime,
    access_token: str | None = None,
    raise_on_missing: bool,
    raise_on_invalid: bool,
) -> Principal | None:
    settings = runtime.settings
    if not settings.auth_enabled:
        return Principal(user_id="anonymous")
    token = credentials.credentials if credentials is not None else access_token
    if not token:
        if raise_on_missing:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing bearer token.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return None
    try:
        return decode_access_token(token, settings=settings)
    except AuthError as exc:
        if raise_on_invalid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(exc),
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        return None


def _normalize_claim_values(raw: object) -> set[str]:
    if raw is None:
        return set()
    if isinstance(raw, str):
        return {item for item in raw.replace(",", " ").split() if item}
    if isinstance(raw, Iterable):
        return {str(item).strip() for item in raw if str(item).strip()}
    text = str(raw).strip()
    return {text} if text else set()


def _principal_roles(principal: Principal) -> set[str]:
    claims = principal.claims or {}
    roles = _normalize_claim_values(claims.get("roles"))
    roles.update(_normalize_claim_values(claims.get("role")))

    realm_access = claims.get("realm_access")
    if isinstance(realm_access, dict):
        roles.update(_normalize_claim_values(realm_access.get("roles")))

    resource_access = claims.get("resource_access")
    if isinstance(resource_access, dict):
        for access in resource_access.values():
            if isinstance(access, dict):
                roles.update(_normalize_claim_values(access.get("roles")))
    return roles


def get_current_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> Principal:
    principal = _principal_from_credentials(
        credentials,
        runtime=runtime,
        access_token=request.cookies.get(
            getattr(runtime.settings, "auth_access_cookie_name", _DEFAULT_ACCESS_COOKIE_NAME)
        ),
        raise_on_missing=True,
        raise_on_invalid=True,
    )
    if principal is None:  # Defensive; raise_on_missing keeps this unreachable.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal


def get_optional_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> Principal | None:
    return _principal_from_credentials(
        credentials,
        runtime=runtime,
        access_token=request.cookies.get(
            getattr(runtime.settings, "auth_access_cookie_name", _DEFAULT_ACCESS_COOKIE_NAME)
        ),
        raise_on_missing=False,
        raise_on_invalid=False,
    )


def get_current_user(
    request: Request,
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
    user_service: UserService = Depends(get_user_service),
) -> User:
    try:
        return user_service.ensure_user_from_principal(
            principal,
            allow_admin_bootstrap=allow_implicit_admin_bootstrap(runtime.settings),
            bootstrap_admin_user_ids=runtime.settings.auth_bootstrap_admin_user_ids,
            request_id=getattr(request.state, "request_id", None),
        )
    except UserInactiveError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc


def get_current_auth_context(
    principal: Principal = Depends(get_current_principal),
    user: User = Depends(get_current_user),
) -> AuthContext:
    permissions = permissions_for_roles(user.roles)
    return AuthContext(
        principal=principal,
        user=user,
        permissions=permissions,
        is_admin=is_admin_role(user.roles),
    )


def require_admin_user(
    context: AuthContext = Depends(get_current_auth_context),
) -> AuthContext:
    if not context.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin permission is required.",
        )
    return context


def require_permission(permission: str) -> Callable[[AuthContext], AuthContext]:
    def dependency(
        context: AuthContext = Depends(get_current_auth_context),
    ) -> AuthContext:
        if permission not in context.permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission: {permission}.",
            )
        return context

    return dependency


def require_scopes(*scopes: str) -> Callable[[Principal], Principal]:
    required_scopes = tuple(scope for scope in scopes if scope)

    def dependency(
        principal: Principal = Depends(get_current_principal),
        runtime: AppRuntime = Depends(get_app_runtime),
    ) -> Principal:
        if not runtime.settings.auth_enabled:
            return principal
        missing = [scope for scope in required_scopes if scope not in principal.scopes]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required scope: {', '.join(missing)}.",
            )
        return principal

    return dependency


def require_roles(*roles: str) -> Callable[[Principal], Principal]:
    required_roles = tuple(role for role in roles if role)

    def dependency(
        principal: Principal = Depends(get_current_principal),
        runtime: AppRuntime = Depends(get_app_runtime),
    ) -> Principal:
        if not runtime.settings.auth_enabled:
            return principal
        principal_roles = _principal_roles(principal)
        missing = [role for role in required_roles if role not in principal_roles]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required role: {', '.join(missing)}.",
            )
        return principal

    return dependency


get_runtime = get_app_runtime


__all__ = [
    "get_app_runtime",
    "get_chat_service",
    "get_auth_service",
    "get_current_auth_context",
    "get_current_principal",
    "get_current_user",
    "get_optional_principal",
    "get_runtime",
    "get_user_service",
    "allow_implicit_admin_bootstrap",
    "require_admin_user",
    "require_permission",
    "require_roles",
    "require_scopes",
    "security",
]
