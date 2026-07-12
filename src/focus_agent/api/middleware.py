from __future__ import annotations

import logging
import secrets
import time
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp

from focus_agent.api.errors import _build_envelope
from focus_agent.config import Settings
from focus_agent.core.repo_call import has_repo_method
from focus_agent.security.tokens import AuthError, decode_access_token
from focus_agent.services.coordination import InMemoryRateLimitBackend, RateLimitBackend

REQUEST_ID_HEADER = "X-Request-ID"
CSRF_TOKEN_HEADER = "X-CSRF-Token"
CSRF_TOKEN_COOKIE = "focus_agent_csrf"
RATE_LIMITED_PATH_PREFIXES = ("/v2/threads",)
_CSRF_PROTECTED_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_DEVELOPMENT_ENVIRONMENTS = frozenset({"dev", "development", "local", "test", "testing", "ci"})
logger = logging.getLogger("focus_agent.api")


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach a request id to each request for tracing and log correlation."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid4().hex
        request.state.request_id = request_id
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000.0
        response.headers[REQUEST_ID_HEADER] = request_id
        logger.info(
            "request_completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
            },
        )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Apply sliding-window rate limiting per client identity.

    Chat endpoints get a stricter limit than other routes because they trigger
    expensive LLM calls. Authenticated principals are keyed by user id; anonymous
    requests fall back to the source IP.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        default_limit: int,
        chat_limit: int,
        settings: Settings,
    ) -> None:
        super().__init__(app)
        self._default_limit = default_limit
        self._chat_limit = chat_limit
        self._settings = settings
        self._limiter = InMemoryRateLimitBackend()

    def _identity(self, request: Request) -> str:
        auth_header = request.headers.get("authorization") or ""
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
            if token:
                try:
                    principal = decode_access_token(token, settings=self._settings)
                except AuthError:
                    pass
                else:
                    if principal.tenant_id:
                        return f"principal:{principal.tenant_id}:{principal.user_id}"
                    return f"principal:{principal.user_id}"
        client = request.client
        return f"ip:{client.host}" if client else "anonymous"

    def _resolve_limit(self, path: str) -> int:
        for prefix in RATE_LIMITED_PATH_PREFIXES:
            if path.startswith(prefix):
                return self._chat_limit
        return self._default_limit

    def _rate_limit_backend(self, request: Request) -> RateLimitBackend:
        runtime = getattr(getattr(request.app, "state", None), "runtime", None)
        coordination_backend = getattr(runtime, "coordination_backend", None)
        backend = getattr(coordination_backend, "rate_limiter", None)
        if has_repo_method(backend, "check"):
            return backend
        return self._limiter

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method in {"OPTIONS", "HEAD"}:
            return await call_next(request)
        limit = self._resolve_limit(request.url.path)
        identity = self._identity(request)
        bucket_scope = (
            "chat"
            if any(request.url.path.startswith(prefix) for prefix in RATE_LIMITED_PATH_PREFIXES)
            else request.url.path
        )
        bucket_key = f"{identity}:{bucket_scope}"
        result = self._rate_limit_backend(request).check(
            key=bucket_key, limit=limit, window_seconds=60.0
        )
        if not result.allowed:
            retry_after = max(1, int(round(result.retry_after_seconds)))
            details = {
                "retry_after_seconds": retry_after,
                "limit_per_minute": limit,
            }
            return JSONResponse(
                status_code=429,
                content=_build_envelope(
                    code=429,
                    message="Rate limit exceeded. Retry later.",
                    request_id=getattr(request.state, "request_id", None),
                    data=details,
                    retryable=True,
                ),
                headers={"Retry-After": str(retry_after)},
            )
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(result.remaining)
        return response


def _normalized_origin(raw_url: str) -> tuple[str, str, int | None] | None:
    try:
        parsed = urlsplit(raw_url)
        port = parsed.port
    except ValueError:
        return None
    scheme = parsed.scheme.lower()
    hostname = parsed.hostname
    if scheme not in {"http", "https"} or not hostname or parsed.username or parsed.password:
        return None
    if port is None:
        port = 443 if scheme == "https" else 80
    return scheme, hostname.lower(), port


class CsrfProtectionMiddleware(BaseHTTPMiddleware):
    """Reject cross-origin mutations that would authenticate with a cookie."""

    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        super().__init__(app)
        self._settings = settings

    def _uses_cookie_auth(self, request: Request) -> bool:
        if not self._settings.auth_enabled:
            return False
        authorization = (request.headers.get("authorization") or "").strip()
        if authorization.lower().startswith("bearer "):
            bearer_token = authorization[7:].strip()
            if bearer_token:
                try:
                    decode_access_token(bearer_token, settings=self._settings)
                except AuthError:
                    pass
                else:
                    return False
        return any(
            request.cookies.get(cookie_name)
            for cookie_name in (
                self._settings.auth_access_cookie_name,
                self._settings.auth_refresh_cookie_name,
            )
        )

    @staticmethod
    def _has_valid_double_submit_token(request: Request) -> bool:
        cookie_token = request.cookies.get(CSRF_TOKEN_COOKIE) or ""
        header_token = request.headers.get(CSRF_TOKEN_HEADER) or ""
        return bool(cookie_token and header_token) and secrets.compare_digest(
            cookie_token, header_token
        )

    def _allows_legacy_request_without_browser_metadata(self) -> bool:
        environment = str(self._settings.app_environment or "").strip().lower()
        return environment in _DEVELOPMENT_ENVIRONMENTS

    def _is_allowed(self, request: Request) -> bool:
        fetch_site = (request.headers.get("sec-fetch-site") or "").strip().lower()
        if fetch_site and fetch_site != "same-origin":
            return False

        request_origin = _normalized_origin(str(request.base_url))
        source_headers = tuple(
            value.strip()
            for value in (
                request.headers.get("origin"),
                request.headers.get("referer"),
            )
            if value
        )
        if source_headers:
            return request_origin is not None and all(
                _normalized_origin(source_header) == request_origin
                for source_header in source_headers
            )

        if fetch_site == "same-origin":
            return True
        if self._has_valid_double_submit_token(request):
            return True
        return self._allows_legacy_request_without_browser_metadata()

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method not in _CSRF_PROTECTED_METHODS or not self._uses_cookie_auth(request):
            return await call_next(request)
        if self._is_allowed(request):
            return await call_next(request)
        return JSONResponse(
            status_code=403,
            content=_build_envelope(
                code=403,
                message="Cross-site cookie-authenticated mutation rejected.",
                request_id=getattr(request.state, "request_id", None),
                data={"code": "csrf_validation_failed"},
                retryable=False,
            ),
        )


def configure_middleware(app: FastAPI, *, settings: Settings) -> None:
    """Wire CORS, CSRF protection, request id, and rate limiting."""
    if settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_allowed_origins),
            allow_credentials=settings.cors_allow_credentials,
            allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", REQUEST_ID_HEADER],
            expose_headers=[REQUEST_ID_HEADER, "X-RateLimit-Limit", "X-RateLimit-Remaining"],
        )

    if settings.rate_limit_enabled:
        app.add_middleware(
            RateLimitMiddleware,
            default_limit=settings.rate_limit_per_minute,
            chat_limit=settings.rate_limit_chat_per_minute,
            settings=settings,
        )

    app.add_middleware(CsrfProtectionMiddleware, settings=settings)
    app.add_middleware(RequestIdMiddleware)


__all__ = [
    "configure_middleware",
    "CSRF_TOKEN_COOKIE",
    "CSRF_TOKEN_HEADER",
    "REQUEST_ID_HEADER",
]
