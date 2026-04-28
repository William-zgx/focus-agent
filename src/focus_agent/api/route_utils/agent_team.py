from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from focus_agent.engine.runtime import AppRuntime


def _agent_team_service_or_503(runtime: AppRuntime | Any):
    service = getattr(runtime, "agent_team_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Agent team service is unavailable.")
    return service


def _agent_team_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))



__all__ = [
    "_agent_team_error",
    "_agent_team_service_or_503",
]
