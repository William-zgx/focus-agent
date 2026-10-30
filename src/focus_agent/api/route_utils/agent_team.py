from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any, NoReturn

from fastapi import HTTPException, status

from focus_agent.engine.runtime import AppRuntime
from focus_agent.services.agent_team_readiness import build_agent_team_readiness

from ..contract_models.agent_team import (
    AgentTeamReadinessCapabilities,
    AgentTeamReadinessResponse,
)
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


def agent_team_capability(service: object, method_name: str) -> bool:
    return callable(getattr(service, method_name, None))


def agent_team_v2_capabilities(service: object) -> AgentTeamReadinessCapabilities:
    capability_provider = getattr(service, "agent_team_v2_capabilities", None)
    configured = capability_provider() if callable(capability_provider) else {}
    if not isinstance(configured, dict):
        configured = {}
    return AgentTeamReadinessCapabilities(
        task_run_queries=bool(
            configured.get(
                "task_run_queries",
                agent_team_capability(service, "get_task_run")
                and agent_team_capability(service, "list_task_runs"),
            )
        ),
        evidence_queries=bool(
            configured.get(
                "evidence_queries",
                agent_team_capability(service, "list_evidence_records"),
            )
        ),
        revision_commands=bool(
            configured.get(
                "revision_commands",
                agent_team_capability(service, "execute_revision_command"),
            )
        ),
    )


def agent_team_v2_readiness(
    runtime: AppRuntime,
    service: object,
) -> AgentTeamReadinessResponse:
    capabilities = agent_team_v2_capabilities(service)
    readiness = build_agent_team_readiness(
        getattr(service, "settings", None) or runtime.settings,
        runtime=runtime,
    )
    phase = str(readiness.get("phase") or "disabled")
    ready = phase == "ready" and capabilities.task_run_queries and capabilities.evidence_queries
    if ready:
        state = "ready"
        detail = None
    elif phase == "disabled":
        state = "disabled"
        detail = "Agent Team v2 rollout is disabled by configuration."
    else:
        state = "degraded"
        blocker_codes = [
            str(blocker.get("code"))
            for blocker in readiness.get("blockers", [])
            if isinstance(blocker, dict) and blocker.get("code")
        ]
        detail = "Agent Team v2 rollout is not ready" + (
            f": {', '.join(blocker_codes)}." if blocker_codes else "."
        )
    return AgentTeamReadinessResponse(
        status=state,
        ready=ready,
        enabled=bool(getattr(getattr(service, "settings", None), "agent_team_v2_enabled", False)),
        service_available=True,
        capabilities=capabilities,
        detail=detail,
    )


def agent_team_v2_method_or_501(service: object, method_name: str):
    method = getattr(service, method_name, None)
    if not callable(method):
        raise agent_team_v2_not_implemented(method_name)
    return method


__all__ = [
    "_agent_team_service_or_503",
    "agent_team_capability",
    "agent_team_errors",
    "agent_team_v2_capabilities",
    "agent_team_v2_errors",
    "agent_team_v2_method_or_501",
    "agent_team_v2_not_implemented",
    "agent_team_v2_readiness",
]
