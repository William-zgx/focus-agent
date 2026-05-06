from __future__ import annotations

from typing import Any, Iterable

from pydantic import Field

from ..agent_roles import AgentRole, normalize_agent_role
from ..core.types import StateModel
from .tool_registry import ToolRegistry, ToolRuntimeMeta


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
    intent_policies: list[str] = Field(default_factory=list)
    intent_tags: list[str] = Field(default_factory=list)
    sensitive_args: list[str] = Field(default_factory=list)
    redaction_policy: str = "mask"
    provider_id: str | None = None


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


class CapabilityPolicyEngine:
    def allow_tool(
        self,
        capability: CapabilityDescriptor,
        *,
        role: AgentRole | str,
        tool_policy: str,
    ) -> tuple[bool, str]:
        normalized_role = normalize_agent_role(role)
        normalized_policy = (tool_policy or "execution").strip().lower()
        if normalized_policy == "direct_answer":
            return False, "direct_answer_policy"
        if normalized_policy != "execution" and normalized_policy not in capability.intent_policies:
            return False, f"policy_not_allowed:{normalized_policy}"
        if normalized_policy == "workspace_lookup":
            if capability.requires_network:
                return False, "workspace_lookup_no_network"
            if capability.requires_workspace_write:
                return False, "workspace_lookup_no_workspace_write"
        if normalized_policy == "live_web_research" and capability.requires_workspace_write:
            return False, "live_web_research_no_workspace_write"
        if normalized_role.value not in capability.allowed_roles:
            return False, f"role_not_allowed:{normalized_role.value}"
        if normalized_role == AgentRole.CRITIC and capability.requires_workspace_write:
            return False, "critic_no_workspace_write"
        if capability.toolset == "memory" and capability.side_effect:
            return False, "memory_write_reserved"
        if capability.requires_approval:
            return True, "approval_required"
        return True, "allowed"

    def tool_allowed(
        self,
        tool: Any,
        *,
        role: AgentRole | str,
        tool_policy: str,
    ) -> tuple[bool, str]:
        return self.allow_tool(
            capability_from_tool(
                name=str(getattr(tool, "name", "")).strip(),
                description=str(getattr(tool, "description", "") or ""),
                runtime=ToolRuntimeMeta.from_tool(tool),
            ),
            role=role,
            tool_policy=tool_policy,
        )


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
    return CapabilityDescriptor(
        name=name,
        description=description,
        toolset=runtime.toolset,
        allowed_roles=list(runtime.allowed_roles),
        risk_level=runtime.risk_level or _default_risk_level(runtime),
        side_effect=runtime.side_effect,
        parallel_safe=runtime.parallel_safe,
        cacheable=runtime.cacheable,
        requires_network=runtime.requires_network,
        requires_workspace_write=runtime.requires_workspace_write
        or runtime.side_effect_kind == "workspace_write",
        requires_approval=runtime.requires_approval,
        intent_policies=list(runtime.intent_policies),
        intent_tags=list(runtime.intent_tags),
        sensitive_args=list(runtime.sensitive_args),
        redaction_policy=runtime.redaction_policy,
        provider_id=runtime.provider_id,
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
    policy_engine = CapabilityPolicyEngine()
    decisions: list[ToolRouteDecision] = []
    for name in available:
        capability = capabilities.get(name)
        if capability is None:
            decisions.append(ToolRouteDecision(name=name, allowed=False, reason="unknown_tool"))
            continue
        allowed, reason = policy_engine.allow_tool(
            capability,
            role=normalized_role,
            tool_policy=tool_policy,
        )
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


def _default_risk_level(runtime: ToolRuntimeMeta) -> str:
    if runtime.requires_approval:
        return "high"
    if runtime.side_effect or runtime.requires_workspace_write:
        return "medium"
    return "low"


__all__ = [
    "CapabilityPolicyEngine",
    "CapabilityDescriptor",
    "ToolRouteDecision",
    "ToolRoutePlan",
    "build_capability_registry",
    "build_tool_route_plan",
    "infer_tool_router_role",
]
