from __future__ import annotations

from collections.abc import Iterable

from pydantic import Field

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


_TOOLSET_DESCRIPTIONS = {
    "artifact": "Draft and iterate explicit user-visible artifacts.",
    "memory": "Read and manage durable memory and conversation recovery state.",
    "skill": "Inspect reusable local and bundled workflow instructions.",
    "web": "Retrieve live web evidence and URL content.",
    "workspace": "Inspect repository files, code, and git state.",
}
_RISK_ORDER = {"low": 0, "medium": 1, "high": 2}


def build_capability_registry(tool_registry: ToolRegistry) -> list[CapabilityDescriptor]:
    descriptors: list[CapabilityDescriptor] = []
    for tool in tuple(tool_registry.tools):
        name = str(getattr(tool, "name", "")).strip()
        if not name:
            continue
        runtime = tool_registry.runtime_by_name.get(name) or ToolRuntimeMeta()
        descriptors.append(
            capability_from_tool(
                name=name,
                description=str(getattr(tool, "description", "") or ""),
                runtime=runtime,
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
                provider_ids=_sorted_unique(
                    capability.provider_id for capability in capabilities if capability.provider_id
                ),
                risk_levels=sorted(
                    {capability.risk_level for capability in capabilities if capability.risk_level},
                    key=lambda item: (_RISK_ORDER.get(item, 99), item),
                ),
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


def _sorted_unique(values: Iterable[str | None]) -> list[str]:
    return sorted({str(value).strip() for value in values if str(value or "").strip()})


def _default_risk_level(runtime: ToolRuntimeMeta) -> str:
    if runtime.requires_approval:
        return "high"
    if runtime.side_effect or runtime.requires_workspace_write:
        return "medium"
    return "low"


__all__ = [
    "CapabilityDescriptor",
    "ToolsetDescriptor",
    "build_capability_registry",
    "build_toolset_registry",
    "capability_from_tool",
]
