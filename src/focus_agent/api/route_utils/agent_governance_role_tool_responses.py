from __future__ import annotations

from typing import Any

from focus_agent.capabilities.catalog import build_capability_registry, build_toolset_registry
from focus_agent.engine.runtime import AppRuntime

from ..contracts import AgentCapabilityListResponse, AgentToolsetListResponse


def _agent_capabilities_response(runtime: AppRuntime | Any) -> AgentCapabilityListResponse:
    registry = getattr(runtime, "tool_registry", None)
    items = build_capability_registry(registry) if registry is not None else []
    return AgentCapabilityListResponse(
        items=[item.model_dump(mode="json") for item in items],
        count=len(items),
    )


def _agent_toolsets_response(runtime: AppRuntime | Any) -> AgentToolsetListResponse:
    registry = getattr(runtime, "tool_registry", None)
    items = build_toolset_registry(registry) if registry is not None else []
    return AgentToolsetListResponse(
        items=[item.model_dump(mode="json") for item in items],
        count=len(items),
    )


__all__ = ["_agent_capabilities_response", "_agent_toolsets_response"]
