from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

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
    usage_examples: list[str] = Field(default_factory=list)
    negative_examples: list[str] = Field(default_factory=list)
    max_calls_per_turn: int | None = None
    output_summary_contract: str | None = None
    sensitive_args: list[str] = Field(default_factory=list)
    redaction_policy: str = "mask"
    provider_id: str | None = None


class ToolsetDescriptor(StateModel):
    name: str
    description: str = ""
    tools: list[str] = Field(default_factory=list)
    count: int = 0
    provider_ids: list[str] = Field(default_factory=list)
    risk_levels: list[str] = Field(default_factory=list)
    allowed_roles: list[str] = Field(default_factory=list)
    intent_policies: list[str] = Field(default_factory=list)
    requires_network: bool = False
    requires_workspace_write: bool = False
    side_effect: bool = False
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
    intent_source: str | None = None
    confidence: float | None = None
    reason_codes: list[str] = Field(default_factory=list)
    preferred_first_tool: str | None = None
    preferred_first_args: dict[str, Any] = Field(default_factory=dict)
    allowed_tools: list[str] = Field(default_factory=list)
    denied_tools: list[str] = Field(default_factory=list)
    decisions: list[ToolRouteDecision] = Field(default_factory=list)


class ToolIntentPlan(StateModel):
    normalized_text: str = ""
    policy: str = "direct_answer"
    confidence: float = 0.55
    reason_codes: list[str] = Field(default_factory=list)
    preferred_first_tool: str | None = None
    preferred_first_args: dict[str, Any] = Field(default_factory=dict)
    allowed_toolsets: list[str] = Field(default_factory=list)
    denied_toolsets: list[str] = Field(default_factory=list)
    source: str = "deterministic"
    temporal_anchor_required: bool = False
    temporal_anchor_forced: bool = False
    external_answer_missing_citation: bool = False


_TOOLSET_DESCRIPTIONS = {
    "artifact": "Draft and iterate explicit user-visible artifacts.",
    "memory": "Read and manage durable memory and conversation recovery state.",
    "skill": "Inspect reusable local and bundled workflow instructions.",
    "web": "Retrieve live web evidence and URL content.",
    "workspace": "Inspect repository files, code, and git state.",
}
_RISK_ORDER = {"low": 0, "medium": 1, "high": 2}


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
        descriptors.append(
            capability_from_tool(
                name=name, description=str(getattr(tool, "description", "") or ""), runtime=runtime
            )
        )
    return sorted(descriptors, key=lambda item: item.name)


def build_toolset_registry(tool_registry: ToolRegistry) -> list[ToolsetDescriptor]:
    grouped: dict[str, list[CapabilityDescriptor]] = {}
    for capability in build_capability_registry(tool_registry):
        toolset = capability.toolset or f"ungrouped:{capability.name}"
        grouped.setdefault(toolset, []).append(capability)

    descriptors: list[ToolsetDescriptor] = []
    for name, capabilities in grouped.items():
        tools = sorted(capability.name for capability in capabilities)
        provider_ids = _sorted_unique(
            capability.provider_id for capability in capabilities if capability.provider_id
        )
        risk_levels = sorted(
            {capability.risk_level for capability in capabilities if capability.risk_level},
            key=lambda item: (_RISK_ORDER.get(item, 99), item),
        )
        descriptors.append(
            ToolsetDescriptor(
                name=name,
                description=_TOOLSET_DESCRIPTIONS.get(
                    name,
                    "Provider-defined tool group."
                    if not name.startswith("ungrouped:")
                    else "Tool without a declared toolset.",
                ),
                tools=tools,
                count=len(tools),
                provider_ids=provider_ids,
                risk_levels=risk_levels,
                allowed_roles=_sorted_unique(
                    role for capability in capabilities for role in capability.allowed_roles
                ),
                intent_policies=_sorted_unique(
                    policy for capability in capabilities for policy in capability.intent_policies
                ),
                requires_network=any(capability.requires_network for capability in capabilities),
                requires_workspace_write=any(
                    capability.requires_workspace_write for capability in capabilities
                ),
                side_effect=any(capability.side_effect for capability in capabilities),
                requires_approval=any(capability.requires_approval for capability in capabilities),
            )
        )
    return sorted(descriptors, key=lambda item: (item.name.startswith("ungrouped:"), item.name))


def capability_from_tool(
    *, name: str, description: str, runtime: ToolRuntimeMeta
) -> CapabilityDescriptor:
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
        usage_examples=list(runtime.usage_examples),
        negative_examples=list(runtime.negative_examples),
        max_calls_per_turn=runtime.max_calls_per_turn,
        output_summary_contract=runtime.output_summary_contract,
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
    exposed_tool_names: Iterable[str] | None = None,
    confidence: float | None = None,
    reason_codes: Iterable[str] | None = None,
    intent_source: str | None = None,
    preferred_first_tool: str | None = None,
    preferred_first_args: Mapping[str, Any] | None = None,
    enforce: bool = True,
) -> ToolRoutePlan:
    normalized_role = normalize_agent_role(role)
    available = _normalized_tool_names(available_tool_names)
    exposed = (
        set(_normalized_tool_names(exposed_tool_names)) if exposed_tool_names is not None else None
    )
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
        if allowed and exposed is not None and name not in exposed:
            allowed = False
            reason = "not_exposed_by_turn_policy"
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
        intent_source=intent_source,
        confidence=confidence,
        reason_codes=[str(item) for item in reason_codes or () if str(item).strip()],
        preferred_first_tool=preferred_first_tool,
        preferred_first_args=dict(preferred_first_args or {}),
        allowed_tools=[item.name for item in decisions if item.allowed],
        denied_tools=[item.name for item in decisions if not item.allowed],
        decisions=decisions,
    )


def _normalized_tool_names(names: Iterable[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_name in names or ():
        name = str(raw_name).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        normalized.append(name)
    return normalized


def _sorted_unique(values: Iterable[str | None]) -> list[str]:
    return sorted({str(value).strip() for value in values if str(value or "").strip()})


def infer_tool_router_role(
    role_route_plan: dict[str, Any] | None, *, fallback: AgentRole = AgentRole.EXECUTOR
) -> AgentRole:
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
    "ToolsetDescriptor",
    "ToolRouteDecision",
    "ToolIntentPlan",
    "ToolRoutePlan",
    "build_capability_registry",
    "build_toolset_registry",
    "build_tool_route_plan",
    "infer_tool_router_role",
]
