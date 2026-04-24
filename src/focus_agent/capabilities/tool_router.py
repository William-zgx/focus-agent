from __future__ import annotations

from typing import Any, Iterable

from pydantic import Field

from ..agent_roles import AgentRole, normalize_agent_role
from ..core.types import StateModel
from .tool_registry import ToolRegistry, ToolRuntimeMeta

_NETWORK_TOOLS = {"web_search", "web_fetch"}
_WORKSPACE_WRITE_TOOLS = {"write_text_artifact", "artifact_update"}
_MEMORY_WRITE_TOOLS = {"memory_save", "memory_forget"}
_ROLE_DEFAULTS: dict[AgentRole, set[str]] = {
    AgentRole.ORCHESTRATOR: {"conversation_summary", "skills_list", "skill_view"},
    AgentRole.PLANNER: {
        "web_search",
        "web_fetch",
        "current_utc_time",
        "search_code",
        "read_file",
        "conversation_summary",
        "skills_list",
        "skill_view",
    },
    AgentRole.EXECUTOR: {
        "list_files",
        "read_file",
        "search_code",
        "codebase_stats",
        "git_status",
        "git_diff",
        "artifact_list",
        "artifact_read",
        "artifact_update",
        "write_text_artifact",
    },
    AgentRole.CRITIC: {
        "list_files",
        "read_file",
        "search_code",
        "git_status",
        "git_diff",
        "git_log",
        "artifact_list",
        "artifact_read",
    },
    AgentRole.MEMORY_CURATOR: {
        "memory_search",
        "conversation_summary",
        "artifact_list",
        "artifact_read",
    },
    AgentRole.SKILL_SCOUT: {
        "skills_list",
        "skill_view",
        "conversation_summary",
    },
}


class CapabilityDescriptor(StateModel):
    name: str
    description: str = ""
    toolset: str | None = None
    allowed_roles: list[str] = Field(default_factory=list)
    risk_level: str = "low"
    side_effect: bool = False
    parallel_safe: bool = False
    cacheable: bool = False
    requires_network: bool = False
    requires_workspace_write: bool = False
    requires_approval: bool = False


class ToolRouteDecision(StateModel):
    name: str
    allowed: bool
    reason: str
    risk_level: str = "low"
    toolset: str | None = None


class ToolRoutePlan(StateModel):
    enabled: bool = False
    enforce: bool = True
    role: str = AgentRole.EXECUTOR.value
    tool_policy: str = "execution"
    allowed_tools: list[str] = Field(default_factory=list)
    denied_tools: list[str] = Field(default_factory=list)
    decisions: list[ToolRouteDecision] = Field(default_factory=list)


def build_capability_registry(tool_registry: ToolRegistry) -> list[CapabilityDescriptor]:
    descriptors: list[CapabilityDescriptor] = []
    for tool in tuple(tool_registry.tools):
        name = str(getattr(tool, "name", "")).strip()
        if not name:
            continue
        runtime = tool_registry.runtime_by_name.get(name) or ToolRuntimeMeta()
        descriptors.append(capability_from_tool(name=name, description=str(getattr(tool, "description", "") or ""), runtime=runtime))
    return sorted(descriptors, key=lambda item: item.name)


def capability_from_tool(*, name: str, description: str, runtime: ToolRuntimeMeta) -> CapabilityDescriptor:
    allowed_roles = list(runtime.allowed_roles) or [
        role.value
        for role, tool_names in _ROLE_DEFAULTS.items()
        if name in tool_names
    ]
    return CapabilityDescriptor(
        name=name,
        description=description,
        toolset=runtime.toolset or _default_toolset(name),
        allowed_roles=allowed_roles,
        risk_level=runtime.risk_level or _default_risk_level(name, runtime),
        side_effect=runtime.side_effect,
        parallel_safe=runtime.parallel_safe,
        cacheable=runtime.cacheable,
        requires_network=name in _NETWORK_TOOLS,
        requires_workspace_write=name in _WORKSPACE_WRITE_TOOLS or runtime.side_effect_kind == "workspace_write",
        requires_approval=runtime.requires_approval,
    )


def build_tool_route_plan(
    *,
    tool_registry: ToolRegistry,
    role: AgentRole | str,
    tool_policy: str,
    available_tool_names: Iterable[str],
    enforce: bool = True,
) -> ToolRoutePlan:
    normalized_role = normalize_agent_role(role)
    available = [str(name).strip() for name in available_tool_names if str(name).strip()]
    capabilities = {item.name: item for item in build_capability_registry(tool_registry)}
    decisions: list[ToolRouteDecision] = []
    for name in available:
        capability = capabilities.get(name)
        if capability is None:
            decisions.append(ToolRouteDecision(name=name, allowed=False, reason="unknown_tool"))
            continue
        allowed, reason = _allow_tool(capability, role=normalized_role, tool_policy=tool_policy)
        decisions.append(
            ToolRouteDecision(
                name=name,
                allowed=allowed,
                reason=reason,
                risk_level=capability.risk_level,
                toolset=capability.toolset,
            )
        )
    return ToolRoutePlan(
        enabled=True,
        enforce=enforce,
        role=normalized_role.value,
        tool_policy=tool_policy,
        allowed_tools=[item.name for item in decisions if item.allowed],
        denied_tools=[item.name for item in decisions if not item.allowed],
        decisions=decisions,
    )


def infer_tool_router_role(role_route_plan: dict[str, Any] | None, *, fallback: AgentRole = AgentRole.EXECUTOR) -> AgentRole:
    if isinstance(role_route_plan, dict):
        for raw in role_route_plan.get("decisions") or []:
            if not isinstance(raw, dict):
                continue
            role = str(raw.get("role") or "")
            if role and role != AgentRole.ORCHESTRATOR.value:
                try:
                    return normalize_agent_role(role)
                except ValueError:
                    continue
    return fallback


def _allow_tool(capability: CapabilityDescriptor, *, role: AgentRole, tool_policy: str) -> tuple[bool, str]:
    normalized_policy = (tool_policy or "execution").strip().lower()
    if normalized_policy == "direct_answer":
        return False, "direct_answer_policy"
    if normalized_policy == "workspace_lookup" and capability.requires_network:
        return False, "workspace_lookup_no_network"
    if normalized_policy == "live_web_research" and capability.name not in {"web_search", "web_fetch", "current_utc_time"}:
        return False, "live_web_policy"
    if role.value not in capability.allowed_roles:
        return False, f"role_not_allowed:{role.value}"
    if capability.requires_approval:
        return False, "approval_required"
    if role == AgentRole.CRITIC and capability.requires_workspace_write:
        return False, "critic_no_workspace_write"
    if capability.name in _MEMORY_WRITE_TOOLS:
        return False, "memory_write_reserved"
    return True, "allowed"


def _default_toolset(name: str) -> str:
    if name.startswith("web_") or name == "current_utc_time":
        return "web"
    if name.startswith("memory_"):
        return "memory"
    if name.startswith("artifact_") or name == "write_text_artifact":
        return "artifact"
    if name.startswith("git_") or name in {"read_file", "list_files", "search_code", "codebase_stats"}:
        return "workspace"
    if name.startswith("skill"):
        return "skill"
    return "core"


def _default_risk_level(name: str, runtime: ToolRuntimeMeta) -> str:
    if runtime.requires_approval:
        return "high"
    if runtime.side_effect or name in _WORKSPACE_WRITE_TOOLS or name in _MEMORY_WRITE_TOOLS:
        return "medium"
    return "low"


__all__ = [
    "CapabilityDescriptor",
    "ToolRouteDecision",
    "ToolRoutePlan",
    "build_capability_registry",
    "build_tool_route_plan",
    "infer_tool_router_role",
]
