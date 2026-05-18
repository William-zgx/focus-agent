from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from focus_agent.observability.tracing import current_trace_runtime_payload

from .error_codes import ErrorCode, error_code_for_status

logger = logging.getLogger("focus_agent.api")


class ErrorEnvelope(BaseModel):
    code: int | ErrorCode
    message: str
    details: dict[str, Any] | None = None
    trace_id: str | None = None
    retryable: bool = False
    request_id: str | None = None
    stable_code: ErrorCode | None = Field(default=None)


def _build_envelope(
    *,
    code: int,
    message: str,
    request_id: str | None,
    data: Any = None,
    retryable: bool | None = None,
) -> dict[str, Any]:
    stable_code = error_code_for_status(int(code))
    trace_id = current_trace_runtime_payload().get("trace_id")
    envelope: dict[str, Any] = {
        "code": code,
        "stable_code": stable_code.value,
        "message": message,
        "data": data,
        "details": data if isinstance(data, dict) else None,
        "trace_id": trace_id,
        "retryable": bool(
            retryable if retryable is not None else code in {408, 409, 425, 429, 500, 502, 503, 504}
        ),
    }
    if request_id:
        envelope["request_id"] = request_id
    return envelope


async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    detail = exc.detail
    if isinstance(detail, str):
        message = detail
        data: Any = None
    else:
        message = "Request failed."
        data = detail
    return JSONResponse(
        status_code=exc.status_code,
        content=_build_envelope(
            code=exc.status_code,
            message=message,
            request_id=request_id,
            data=data,
        ),
        headers=exc.headers,
    )


async def _validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=422,
        content=_build_envelope(
            code=422,
            message="Request validation failed.",
            request_id=request_id,
            data={"errors": exc.errors()},
        ),
    )


async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    logger.exception(
        "unhandled_exception",
        extra={
            "request_id": request_id,
            "path": request.url.path,
            "method": request.method,
        },
    )
    return JSONResponse(
        status_code=500,
        content=_build_envelope(
            code=500,
            message="Internal server error.",
            request_id=request_id,
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(HTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)


__all__ = ["ErrorEnvelope", "register_exception_handlers"]
