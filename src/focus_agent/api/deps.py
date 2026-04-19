from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from focus_agent.config import Settings
from focus_agent.engine.runtime import AppRuntime
from focus_agent.engine.runtime import create_runtime
from focus_agent.security.tokens import AuthError, Principal, decode_access_token
from focus_agent.services.chat import ChatService

security = HTTPBearer(auto_error=False)


def _ensure_app_services(request: Request) -> tuple[AppRuntime, ChatService]:
    runtime = getattr(request.app.state, "runtime", None)
    chat_service = getattr(request.app.state, "chat_service", None)
    if runtime is None:
        runtime = create_runtime(Settings.from_env())
        request.app.state.runtime = runtime
    if chat_service is None:
        chat_service = ChatService(runtime)
        request.app.state.chat_service = chat_service
    return runtime, chat_service


def get_app_runtime(request: Request) -> AppRuntime:
    runtime, _ = _ensure_app_services(request)
    return runtime


def get_chat_service(request: Request) -> ChatService:
    _, chat_service = _ensure_app_services(request)
    return chat_service


def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> Principal:
    settings = runtime.settings
    if not settings.auth_enabled:
        return Principal(user_id='anonymous')
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Missing bearer token.',
            headers={'WWW-Authenticate': 'Bearer'},
        )
    try:
        return decode_access_token(credentials.credentials, settings=settings)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={'WWW-Authenticate': 'Bearer'},
        ) from exc


get_runtime = get_app_runtime


__all__ = [
    "get_app_runtime",
    "get_chat_service",
    "get_current_principal",
    "get_runtime",
    "security",
]
