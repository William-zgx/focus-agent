from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from langchain.tools import tool

from ..config import Settings
from ..skills import SkillRegistry
from ..skills.registry import render_skill_view_json, render_skills_list_json
from .default_tools import get_default_tools
from .tool_manifest import StaticToolProvider, ToolManifest, ToolProvider, normalize_tool_metadata

ToolArgValidator = Callable[[Mapping[str, Any]], None]
ToolFallbackHandler = Callable[[Exception, Mapping[str, Any]], Any]


@dataclass(frozen=True, slots=True)
class ToolRuntimeMeta:
    side_effect: bool = False
    parallel_safe: bool = False
    cacheable: bool = False
    cache_scope: str = "thread"
    timeout_seconds: float | None = None
    fallback_group: str | None = None
    fallback_handler: ToolFallbackHandler | None = None
    max_observation_chars: int | None = None
    validator: ToolArgValidator | None = None
    toolset: str | None = None
    risk_level: str = "low"
    allowed_roles: tuple[str, ...] = ()
    requires_approval: bool = False
    side_effect_kind: str | None = None
    requires_network: bool = False
    requires_workspace_write: bool = False
    intent_policies: tuple[str, ...] = ()
    intent_tags: tuple[str, ...] = ()
    provider_id: str | None = None

    @classmethod
    def from_tool(cls, tool_obj: Any) -> ToolRuntimeMeta:
        metadata = getattr(tool_obj, "metadata", None)
        name = str(getattr(tool_obj, "name", "")).strip()
        return cls.from_metadata(name=name, metadata=metadata if isinstance(metadata, dict) else None)

    @classmethod
    def from_manifest(cls, manifest: ToolManifest) -> ToolRuntimeMeta:
        return cls.from_metadata(name=manifest.name, metadata=manifest.metadata)

    @classmethod
    def from_metadata(
        cls,
        *,
        name: str,
        metadata: Mapping[str, Any] | None,
    ) -> ToolRuntimeMeta:
        normalized = normalize_tool_metadata(name=name, metadata=metadata)
        return cls(
            side_effect=bool(normalized.get("side_effect", False)),
            parallel_safe=bool(normalized.get("parallel_safe", False)),
            cacheable=bool(normalized.get("cacheable", False)),
            cache_scope=str(normalized.get("cache_scope") or "thread"),
            timeout_seconds=(
                float(normalized["timeout_seconds"])
                if normalized.get("timeout_seconds") is not None
                else None
            ),
            fallback_group=(
                str(normalized["fallback_group"])
                if normalized.get("fallback_group")
                else None
            ),
            fallback_handler=normalized.get("fallback_handler"),
            max_observation_chars=(
                int(normalized["max_observation_chars"])
                if normalized.get("max_observation_chars") is not None
                else None
            ),
            validator=normalized.get("validator"),
            toolset=(str(normalized["toolset"]) if normalized.get("toolset") else None),
            risk_level=str(normalized.get("risk_level") or "low"),
            allowed_roles=tuple(
                str(role) for role in (normalized.get("allowed_roles") or ()) if str(role)
            ),
            requires_approval=bool(normalized.get("requires_approval", False)),
            side_effect_kind=(
                str(normalized["side_effect_kind"])
                if normalized.get("side_effect_kind")
                else None
            ),
            requires_network=bool(normalized.get("requires_network", False)),
            requires_workspace_write=bool(normalized.get("requires_workspace_write", False)),
            intent_policies=tuple(
                str(policy)
                for policy in (normalized.get("intent_policies") or ())
                if str(policy)
            ),
            intent_tags=tuple(
                str(tag)
                for tag in (normalized.get("intent_tags") or ())
                if str(tag)
            ),
            provider_id=(
                str(normalized["provider_id"])
                if normalized.get("provider_id")
                else None
            ),
        )


@dataclass(slots=True)
class ToolRegistry:
    tools: tuple[Any, ...]
    manifests: tuple[ToolManifest, ...] = ()
    _by_name: dict[str, Any] = field(init=False, repr=False)
    _runtime_by_name: dict[str, ToolRuntimeMeta] = field(init=False, repr=False)
    _manifest_by_name: dict[str, ToolManifest] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._by_name = {tool_.name: tool_ for tool_ in self.tools}
        if not self.manifests:
            self.manifests = tuple(ToolManifest.from_tool(tool_) for tool_ in self.tools)
        self._manifest_by_name = {manifest.name: manifest for manifest in self.manifests}
        for manifest in self.manifests:
            existing = getattr(manifest.tool, "metadata", None)
            manifest.tool.metadata = {
                **(existing if isinstance(existing, dict) else {}),
                **dict(manifest.metadata),
            }
        self._runtime_by_name = {
            name: ToolRuntimeMeta.from_manifest(manifest)
            for name, manifest in self._manifest_by_name.items()
        }

    @property
    def by_name(self) -> dict[str, Any]:
        return self._by_name

    @property
    def runtime_by_name(self) -> dict[str, ToolRuntimeMeta]:
        return self._runtime_by_name

    @property
    def manifest_by_name(self) -> dict[str, ToolManifest]:
        return self._manifest_by_name


def build_tool_registry(
    *,
    settings: Settings,
    skill_registry: SkillRegistry,
    store=None,
    checkpointer=None,
    artifact_metadata_repository=None,
) -> ToolRegistry:
    providers: tuple[ToolProvider, ...] = (
        StaticToolProvider(
            provider_id="builtin",
            tools=tuple(
                get_default_tools(
                    settings,
                    store=store,
                    checkpointer=checkpointer,
                    artifact_metadata_repository=artifact_metadata_repository,
                )
            ),
        ),
        StaticToolProvider(
            provider_id="skill",
            tools=tuple(_build_skill_tools(settings=settings, skill_registry=skill_registry)),
        ),
    )
    all_manifests = _merge_tool_provider_manifests(
        providers,
        metadata_overlay_for=settings.tool_catalog.metadata_overlay_for,
    )
    ordered_names = tuple(
        dict.fromkeys(
            [
                *settings.tool_catalog.manifest_section_names,
                *all_manifests.keys(),
            ]
        )
    )
    ordered_manifests = tuple(
        all_manifests[tool_name]
        for tool_name in ordered_names
        if tool_name in all_manifests
    )
    return ToolRegistry(
        tools=tuple(manifest.tool for manifest in ordered_manifests),
        manifests=ordered_manifests,
    )


def _merge_tool_provider_manifests(
    providers: Iterable[ToolProvider],
    *,
    metadata_overlay_for: Callable[[str], Mapping[str, Any]],
) -> dict[str, ToolManifest]:
    manifests: dict[str, ToolManifest] = {}
    for provider in providers:
        for manifest in provider.tool_manifests():
            manifests[manifest.name] = manifest.with_overlay(metadata_overlay_for(manifest.name))
    return manifests


def _build_skill_tools(*, settings: Settings, skill_registry: SkillRegistry) -> list[Any]:
    @tool
    def skills_list() -> str:
        """List bundled and local skills with their descriptions and trigger prefixes."""
        return render_skills_list_json(skill_registry)

    @tool
    def skill_view(name: str) -> str:
        """Load the full instructions for a named skill."""
        return render_skill_view_json(skill_registry, skill_id=name)

    skills_list.description = settings.tool_catalog.skills_list.description
    skills_list.metadata = {
        "display_name": settings.tool_catalog.skills_list.label,
        "parallel_safe": True,
        "cacheable": True,
        "cache_scope": "thread",
        "max_observation_chars": 6000,
        "toolset": "skill",
        "intent_policies": ("workspace_lookup", "execution"),
    }
    skill_view.description = settings.tool_catalog.skill_view.description
    skill_view.metadata = {
        "display_name": settings.tool_catalog.skill_view.label,
        "parallel_safe": True,
        "cacheable": True,
        "cache_scope": "thread",
        "max_observation_chars": 8000,
        "toolset": "skill",
        "intent_policies": ("workspace_lookup", "execution"),
    }

    tools: list[Any] = []
    if settings.tool_catalog.skills_list.enabled:
        tools.append(skills_list)
    if settings.tool_catalog.skill_view.enabled:
        tools.append(skill_view)
    return tools
