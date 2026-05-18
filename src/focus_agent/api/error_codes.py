from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    AUTH_REQUIRED = "auth_required"
    AUTH_INVALID = "auth_invalid"
    AUTH_FORBIDDEN = "auth_forbidden"
    RESOURCE_NOT_FOUND = "resource_not_found"
    VALIDATION_FAILED = "validation_failed"
    RATE_LIMITED = "rate_limited"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    INTERNAL_ERROR = "internal_error"
    MODEL_PROVIDER_ERROR = "model_provider_error"
    TOOL_TIMEOUT = "tool_timeout"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"


def error_code_for_status(status_code: int) -> ErrorCode:
    if status_code == 401:
        return ErrorCode.AUTH_REQUIRED
    if status_code == 403:
        return ErrorCode.AUTH_FORBIDDEN
    if status_code == 404:
        return ErrorCode.RESOURCE_NOT_FOUND
    if status_code == 409:
        return ErrorCode.IDEMPOTENCY_CONFLICT
    if status_code == 422:
        return ErrorCode.VALIDATION_FAILED
    if status_code == 429:
        return ErrorCode.RATE_LIMITED
    if status_code >= 500:
        return ErrorCode.INTERNAL_ERROR
    return ErrorCode.VALIDATION_FAILED


__all__ = ["ErrorCode", "error_code_for_status"]
