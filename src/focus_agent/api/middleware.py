from __future__ import annotations

import logging
import time
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp

from focus_agent.config import Settings
from focus_agent.security.rate_limit import SlidingWindowRateLimiter


REQUEST_ID_HEADER = "X-Request-ID"
RATE_LIMITED_PATH_PREFIXES = ("/v1/chat",)
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
    ) -> None:
        super().__init__(app)
        self._default_limit = default_limit
        self._chat_limit = chat_limit
        self._limiter = SlidingWindowRateLimiter(window_seconds=60.0)

    def _identity(self, request: Request) -> str:
        auth_header = request.headers.get("authorization") or ""
        if auth_header.lower().startswith("bearer "):
            return f"bearer:{auth_header[7:]}"
        client = request.client
        return f"ip:{client.host}" if client else "anonymous"

    def _resolve_limit(self, path: str) -> int:
        for prefix in RATE_LIMITED_PATH_PREFIXES:
            if path.startswith(prefix):
                return self._chat_limit
        return self._default_limit

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method in {"OPTIONS", "HEAD"}:
            return await call_next(request)
        limit = self._resolve_limit(request.url.path)
        identity = self._identity(request)
        bucket_key = f"{identity}:{request.url.path}"
        result = self._limiter.check(key=bucket_key, limit=limit)
        if not result.allowed:
            retry_after = max(1, int(round(result.retry_after_seconds)))
            return JSONResponse(
                status_code=429,
                content={
                    "code": 429,
                    "message": "Rate limit exceeded. Retry later.",
                    "data": {
                        "retry_after_seconds": retry_after,
                        "limit_per_minute": limit,
                    },
                    "request_id": getattr(request.state, "request_id", None),
                },
                headers={"Retry-After": str(retry_after)},
            )
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(result.remaining)
        return response


def configure_middleware(app: FastAPI, *, settings: Settings) -> None:
    """Wire CORS, request id, and rate-limit middleware on the FastAPI app."""
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
        )

    app.add_middleware(RequestIdMiddleware)


__all__ = ["configure_middleware", "REQUEST_ID_HEADER"]
