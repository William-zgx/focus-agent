from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any, NoReturn

from fastapi import HTTPException, status

from focus_agent.engine.runtime import AppRuntime

from .service_errors import (
    BAD_REQUEST_ERROR_RULE,
    NOT_FOUND_ERROR_RULE,
    PERMISSION_ERROR_RULE,
    ErrorRule,
    map_service_errors,
)

_AGENT_TEAM_ERROR_RULES: tuple[ErrorRule, ...] = (
    NOT_FOUND_ERROR_RULE,
    PERMISSION_ERROR_RULE,
    BAD_REQUEST_ERROR_RULE,
)


def _agent_team_service_or_503(runtime: AppRuntime | Any):
    service = getattr(runtime, "agent_team_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Agent team service is unavailable.")
    return service


def agent_team_errors(*overrides: ErrorRule) -> AbstractContextManager[None]:
    """Map Agent Team service errors to HTTP errors; unexpected errors become a generic 500."""
    return map_service_errors(*overrides, rules=_AGENT_TEAM_ERROR_RULES, unexpected_as_500=True)


def agent_team_v2_not_implemented(method_name: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"Agent Team v2 capability '{method_name}' is not implemented by this service.",
    )


def agent_team_v2_errors(method_name: str, *overrides: ErrorRule) -> AbstractContextManager[None]:
    def _not_implemented(exc: Exception) -> NoReturn:
        raise agent_team_v2_not_implemented(method_name) from exc

    return agent_team_errors((NotImplementedError, _not_implemented), *overrides)


__all__ = [
    "_agent_team_service_or_503",
    "agent_team_errors",
    "agent_team_v2_errors",
    "agent_team_v2_not_implemented",
]
