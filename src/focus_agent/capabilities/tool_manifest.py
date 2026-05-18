from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

_BOOL_METADATA_FIELDS = frozenset(
    {
        "side_effect",
        "parallel_safe",
        "cacheable",
        "requires_network",
        "requires_workspace_write",
        "allow_network",
        "allow_filesystem",
        "requires_approval",
    }
)
_TUPLE_METADATA_FIELDS = frozenset(
    {
        "allowed_roles",
        "intent_policies",
        "intent_tags",
        "negative_examples",
        "sensitive_args",
        "usage_examples",
    }
)
_STRING_METADATA_FIELDS = frozenset(
    {
        "cache_scope",
        "fallback_group",
        "output_summary_contract",
        "toolset",
        "risk_level",
        "side_effect_kind",
        "provider_id",
        "redaction_policy",
    }
)
_INT_METADATA_FIELDS = frozenset(
    {"max_calls_per_turn", "max_observation_chars", "max_concurrent_calls", "max_memory_mb"}
)
_FLOAT_METADATA_FIELDS = frozenset({"timeout_seconds"})


_LEGACY_TOOL_DEFAULTS: dict[str, dict[str, Any]] = {
    "current_utc_time": {
        "toolset": "web",
        "parallel_safe": True,
        "intent_policies": ("live_web_research", "execution"),
        "allowed_roles": ("planner",),
    },
    "web_search": {
        "toolset": "web",
        "requires_network": True,
        "parallel_safe": True,
        "intent_policies": ("live_web_research", "execution"),
        "allowed_roles": ("planner",),
    },
    "web_fetch": {
        "toolset": "web",
        "requires_network": True,
        "parallel_safe": True,
        "intent_policies": ("live_web_research", "execution"),
        "allowed_roles": ("planner",),
    },
    "list_files": {
        "toolset": "workspace",
        "parallel_safe": True,
        "cacheable": True,
        "cache_scope": "thread",
        "intent_policies": ("workspace_lookup", "execution"),
        "intent_tags": ("file_browse",),
        "allowed_roles": ("executor", "critic"),
    },
    "read_file": {
        "toolset": "workspace",
        "parallel_safe": True,
        "cacheable": True,
        "cache_scope": "thread",
        "intent_policies": ("workspace_lookup", "execution"),
        "intent_tags": ("code_search",),
        "allowed_roles": ("planner", "executor", "critic"),
    },
    "search_code": {
        "toolset": "workspace",
        "parallel_safe": True,
        "cacheable": True,
        "cache_scope": "thread",
        "intent_policies": ("workspace_lookup", "execution"),
        "intent_tags": ("code_search",),
        "allowed_roles": ("planner", "executor", "critic"),
    },
    "codebase_stats": {
        "toolset": "workspace",
        "parallel_safe": True,
        "cacheable": True,
        "cache_scope": "thread",
        "intent_policies": ("workspace_lookup", "execution"),
        "allowed_roles": ("executor",),
    },
    "git_status": {
        "toolset": "workspace",
        "parallel_safe": True,
        "intent_policies": ("workspace_lookup", "execution"),
        "allowed_roles": ("executor", "critic"),
    },
    "git_diff": {
        "toolset": "workspace",
        "parallel_safe": True,
        "intent_policies": ("workspace_lookup", "execution"),
        "allowed_roles": ("executor", "critic"),
    },
    "git_log": {
        "toolset": "workspace",
        "parallel_safe": True,
        "intent_policies": ("workspace_lookup", "execution"),
        "allowed_roles": ("critic",),
    },
    "write_text_artifact": {
        "toolset": "artifact",
        "side_effect": True,
        "side_effect_kind": "workspace_write",
        "requires_workspace_write": True,
        "risk_level": "medium",
        "intent_policies": ("execution",),
        "allowed_roles": ("executor",),
    },
    "artifact_list": {
        "toolset": "artifact",
        "parallel_safe": True,
        "intent_policies": ("workspace_lookup", "execution"),
        "allowed_roles": ("executor", "critic", "memory_curator"),
    },
    "artifact_read": {
        "toolset": "artifact",
        "parallel_safe": True,
        "intent_policies": ("workspace_lookup", "execution"),
        "allowed_roles": ("executor", "critic", "memory_curator"),
    },
    "artifact_update": {
        "toolset": "artifact",
        "side_effect": True,
        "side_effect_kind": "workspace_write",
        "requires_workspace_write": True,
        "risk_level": "medium",
        "intent_policies": ("execution",),
        "allowed_roles": ("executor",),
    },
    "memory_save": {
        "toolset": "memory",
        "side_effect": True,
        "risk_level": "medium",
        "intent_policies": ("execution",),
        "allowed_roles": (),
    },
    "memory_search": {
        "toolset": "memory",
        "parallel_safe": True,
        "intent_policies": ("execution",),
        "allowed_roles": ("memory_curator",),
    },
    "memory_forget": {
        "toolset": "memory",
        "side_effect": True,
        "risk_level": "medium",
        "intent_policies": ("execution",),
        "allowed_roles": (),
    },
    "conversation_summary": {
        "toolset": "memory",
        "parallel_safe": True,
        "cacheable": True,
        "cache_scope": "turn",
        "intent_policies": ("workspace_lookup", "execution"),
        "allowed_roles": ("orchestrator", "planner", "memory_curator", "skill_scout"),
    },
    "skills_list": {
        "toolset": "skill",
        "parallel_safe": True,
        "cacheable": True,
        "cache_scope": "thread",
        "intent_policies": ("workspace_lookup", "execution"),
        "allowed_roles": ("orchestrator", "planner", "skill_scout"),
    },
    "skill_view": {
        "toolset": "skill",
        "parallel_safe": True,
        "cacheable": True,
        "cache_scope": "thread",
        "intent_policies": ("workspace_lookup", "execution"),
        "allowed_roles": ("orchestrator", "planner", "skill_scout"),
    },
    "skill_sources": {
        "toolset": "skill",
        "parallel_safe": True,
        "cacheable": True,
        "cache_scope": "thread",
        "intent_policies": ("workspace_lookup", "planning"),
        "allowed_roles": ("orchestrator", "planner", "skill_scout"),
    },
    "skills_search": {
        "toolset": "skill",
        "parallel_safe": True,
        "cacheable": True,
        "cache_scope": "thread",
        "intent_policies": ("workspace_lookup", "planning", "execution"),
        "allowed_roles": ("orchestrator", "planner", "skill_scout"),
    },
    "skill_install": {
        "toolset": "skill",
        "side_effect": True,
        "side_effect_kind": "workspace_write",
        "requires_workspace_write": True,
        "risk_level": "medium",
        "intent_policies": ("planning", "execution"),
        "allowed_roles": ("skill_scout",),
    },
    "skills_refresh_index": {
        "toolset": "skill",
        "side_effect": True,
        "side_effect_kind": "runtime_index_refresh",
        "risk_level": "low",
        "intent_policies": ("workspace_lookup", "planning"),
        "allowed_roles": ("planner", "skill_scout"),
    },
    "notes_create": {
        "toolset": "productivity",
        "side_effect": True,
        "risk_level": "medium",
        "intent_policies": ("execution",),
    },
    "notes_search": {
        "toolset": "productivity",
        "parallel_safe": True,
        "intent_policies": ("workspace_lookup", "execution"),
    },
    "notes_update": {
        "toolset": "productivity",
        "side_effect": True,
        "risk_level": "medium",
        "intent_policies": ("execution",),
    },
    "tasks_create": {
        "toolset": "productivity",
        "side_effect": True,
        "risk_level": "medium",
        "intent_policies": ("execution",),
    },
    "tasks_list": {
        "toolset": "productivity",
        "parallel_safe": True,
        "intent_policies": ("workspace_lookup", "execution"),
    },
    "tasks_update": {
        "toolset": "productivity",
        "side_effect": True,
        "risk_level": "medium",
        "intent_policies": ("execution",),
    },
    "productivity_capture": {
        "toolset": "productivity",
        "side_effect": True,
        "risk_level": "medium",
        "intent_policies": ("execution",),
    },
}


def _split_listish(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


def _copy_metadata_value(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _copy_metadata_value(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [_copy_metadata_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_copy_metadata_value(item) for item in value)
    return value


def _normalize_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in dict(metadata or {}).items():
        key = str(key)
        if key in _BOOL_METADATA_FIELDS:
            normalized[key] = bool(value)
        elif key in _TUPLE_METADATA_FIELDS:
            normalized[key] = _split_listish(value)
        elif key in _STRING_METADATA_FIELDS:
            if value is not None and str(value).strip():
                normalized[key] = str(value).strip()
        elif key in _INT_METADATA_FIELDS:
            if value is not None:
                normalized[key] = int(value)
        elif key in _FLOAT_METADATA_FIELDS:
            if value is not None:
                normalized[key] = float(value)
        else:
            normalized[key] = _copy_metadata_value(value)
    return normalized


def default_tool_metadata(name: str) -> dict[str, Any]:
    return _normalize_metadata(_LEGACY_TOOL_DEFAULTS.get(str(name).strip(), {}))


def normalize_tool_metadata(
    *,
    name: str,
    metadata: Mapping[str, Any] | None = None,
    overlay: Mapping[str, Any] | None = None,
    provider_id: str | None = None,
) -> dict[str, Any]:
    merged = {
        **default_tool_metadata(name),
        **_normalize_metadata(metadata),
        **_normalize_metadata(overlay),
    }
    if provider_id and (provider_id != "builtin" or not merged.get("provider_id")):
        merged["provider_id"] = provider_id
    if merged.get("side_effect_kind") == "workspace_write":
        merged.setdefault("requires_workspace_write", True)
    if merged.get("requires_workspace_write"):
        merged.setdefault("side_effect", True)
        merged.setdefault("risk_level", "medium")
    if merged.get("requires_network"):
        merged.setdefault("toolset", "web")
    if not merged.get("risk_level"):
        merged["risk_level"] = "medium" if merged.get("side_effect") else "low"
    if "allowed_roles" in merged:
        merged["allowed_roles"] = _split_listish(merged.get("allowed_roles"))
    if "intent_policies" in merged:
        merged["intent_policies"] = _split_listish(merged.get("intent_policies"))
    if "intent_tags" in merged:
        merged["intent_tags"] = _split_listish(merged.get("intent_tags"))
    if "sensitive_args" in merged:
        merged["sensitive_args"] = _split_listish(merged.get("sensitive_args"))
    return merged


@dataclass(frozen=True, slots=True)
class ToolManifest:
    name: str
    tool: Any
    provider_id: str = "builtin"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_tool(
        cls,
        tool_obj: Any,
        *,
        provider_id: str = "builtin",
        overlay: Mapping[str, Any] | None = None,
    ) -> ToolManifest:
        name = str(getattr(tool_obj, "name", "")).strip()
        metadata = normalize_tool_metadata(
            name=name,
            metadata=getattr(tool_obj, "metadata", None),
            overlay=overlay,
            provider_id=provider_id,
        )
        return cls(
            name=name,
            tool=tool_obj,
            provider_id=str(metadata.get("provider_id") or provider_id),
            metadata=metadata,
        )

    def with_overlay(self, overlay: Mapping[str, Any] | None) -> ToolManifest:
        if not overlay:
            return self
        return ToolManifest(
            name=self.name,
            tool=self.tool,
            provider_id=self.provider_id,
            metadata=normalize_tool_metadata(
                name=self.name,
                metadata=self.metadata,
                overlay=overlay,
                provider_id=self.provider_id,
            ),
        )


class ToolProvider(Protocol):
    provider_id: str

    def tool_manifests(self) -> Iterable[ToolManifest]:
        """Return manifests for tools provided by this provider."""


@dataclass(frozen=True, slots=True)
class StaticToolProvider:
    provider_id: str
    tools: tuple[Any, ...]

    def tool_manifests(self) -> Iterable[ToolManifest]:
        for tool_obj in self.tools:
            manifest = ToolManifest.from_tool(tool_obj, provider_id=self.provider_id)
            if manifest.name:
                yield manifest


__all__ = [
    "StaticToolProvider",
    "ToolManifest",
    "ToolProvider",
    "default_tool_metadata",
    "normalize_tool_metadata",
]
