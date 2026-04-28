from __future__ import annotations

from collections.abc import Callable, Iterable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from focus_agent.config import Settings
from focus_agent.engine.runtime import AppRuntime
from focus_agent.engine.runtime import create_runtime
from focus_agent.security.tokens import AuthError, Principal, decode_access_token
from focus_agent.services.chat import ChatService, ChatServicePorts

security = HTTPBearer(auto_error=False)


def _ensure_app_services(request: Request) -> tuple[AppRuntime, ChatService]:
    runtime = getattr(request.app.state, "runtime", None)
    chat_service = getattr(request.app.state, "chat_service", None)
    if runtime is None:
        runtime = create_runtime(Settings.from_env())
        request.app.state.runtime = runtime
    if chat_service is None:
        chat_service = ChatService(ChatServicePorts.from_runtime(runtime))
        request.app.state.chat_service = chat_service
    return runtime, chat_service


def get_app_runtime(request: Request) -> AppRuntime:
    runtime, _ = _ensure_app_services(request)
    return runtime


def get_chat_service(request: Request) -> ChatService:
    _, chat_service = _ensure_app_services(request)
    return chat_service


def _principal_from_credentials(
    credentials: HTTPAuthorizationCredentials | None,
    *,
    runtime: AppRuntime,
    raise_on_missing: bool,
    raise_on_invalid: bool,
) -> Principal | None:
    settings = runtime.settings
    if not settings.auth_enabled:
        return Principal(user_id="anonymous")
    if credentials is None:
        if raise_on_missing:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing bearer token.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return None
    try:
        return decode_access_token(credentials.credentials, settings=settings)
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
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> Principal:
    principal = _principal_from_credentials(
        credentials,
        runtime=runtime,
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
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> Principal | None:
    return _principal_from_credentials(
        credentials,
        runtime=runtime,
        raise_on_missing=False,
        raise_on_invalid=False,
    )


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
    "get_current_principal",
    "get_optional_principal",
    "get_runtime",
    "require_roles",
    "require_scopes",
    "security",
]
