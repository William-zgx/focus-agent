from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
import re
from typing import Any, Callable, Mapping

from langchain.tools import tool

from ..config import Settings
from ..skills import SkillRegistry
from ..skills.registry import render_skill_view_json, render_skills_list_json
from .default_tools import get_default_tools
from .tool_manifest import StaticToolProvider, ToolManifest, ToolProvider, normalize_tool_metadata

ToolArgValidator = Callable[[Mapping[str, Any]], None]
ToolFallbackHandler = Callable[[Exception, Mapping[str, Any]], Any]
_PROVIDER_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")


@dataclass(frozen=True, slots=True)
class ToolProviderFactoryContext:
    settings: Settings
    skill_registry: SkillRegistry
    store: Any = None
    checkpointer: Any = None
    artifact_metadata_repository: Any = None


ToolProviderFactory = Callable[[ToolProviderFactoryContext], ToolProvider]


@dataclass(frozen=True, slots=True)
class _RegisteredToolProviderFactory:
    provider_id: str
    factory: ToolProviderFactory
    default_order: int


class ToolProviderFactoryRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, _RegisteredToolProviderFactory] = {}

    def register(
        self,
        provider_id: str,
        factory: ToolProviderFactory,
        *,
        default_order: int,
    ) -> None:
        normalized_provider_id = _normalize_provider_id(provider_id)
        if normalized_provider_id in self._factories:
            raise ValueError(
                f"Tool provider factory {normalized_provider_id!r} is already registered."
            )
        self._factories[normalized_provider_id] = _RegisteredToolProviderFactory(
            provider_id=normalized_provider_id,
            factory=factory,
            default_order=default_order,
        )

    def entries(self) -> tuple[_RegisteredToolProviderFactory, ...]:
        return tuple(self._factories.values())

    def provider_ids(self) -> set[str]:
        return set(self._factories)


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
    sensitive_args: tuple[str, ...] = ()
    redaction_policy: str = "mask"
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
            sensitive_args=tuple(
                str(arg)
                for arg in (normalized.get("sensitive_args") or ())
                if str(arg)
            ),
            redaction_policy=str(normalized.get("redaction_policy") or "mask"),
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
    explicit_providers: Iterable[ToolProvider] | None = None,
    explicit_provider_factories: Mapping[str, ToolProviderFactory] | None = None,
) -> ToolRegistry:
    providers = _build_controlled_tool_provider_registry(
        settings=settings,
        skill_registry=skill_registry,
        store=store,
        checkpointer=checkpointer,
        artifact_metadata_repository=artifact_metadata_repository,
        explicit_providers=explicit_providers,
        explicit_provider_factories=explicit_provider_factories,
    )
    all_manifests = _merge_tool_provider_manifests(
        providers,
        provider_metadata_overlay_for=settings.tool_catalog.provider_metadata_overlay_for,
        provider_overrides_for=settings.tool_catalog.provider_overrides_for,
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


def _build_controlled_tool_provider_registry(
    *,
    settings: Settings,
    skill_registry: SkillRegistry,
    store: Any,
    checkpointer: Any,
    artifact_metadata_repository: Any,
    explicit_providers: Iterable[ToolProvider] | None,
    explicit_provider_factories: Mapping[str, ToolProviderFactory] | None,
) -> tuple[ToolProvider, ...]:
    context = ToolProviderFactoryContext(
        settings=settings,
        skill_registry=skill_registry,
        store=store,
        checkpointer=checkpointer,
        artifact_metadata_repository=artifact_metadata_repository,
    )
    registered: dict[str, tuple[int, ToolProvider]] = {}
    explicit_provider_list = tuple(explicit_providers or ())
    explicit_factory_mapping = dict(explicit_provider_factories or {})
    known_provider_ids = set(_TOOL_PROVIDER_FACTORY_REGISTRY.provider_ids())
    known_provider_ids.update(
        _normalize_provider_id(getattr(provider, "provider_id", ""))
        for provider in explicit_provider_list
    )
    known_provider_ids.update(
        _normalize_provider_id(provider_id)
        for provider_id in explicit_factory_mapping
    )

    for provider_config in settings.tool_catalog.providers:
        if provider_config.enabled and provider_config.id not in known_provider_ids:
            raise ValueError(
                f"Tool provider {provider_config.id!r} is enabled but no provider factory is registered."
            )

    def provider_enabled(provider_id: str) -> bool:
        provider_config = settings.tool_catalog.provider_config_for(provider_id)
        return provider_config is None or provider_config.enabled

    def register(provider: ToolProvider, *, default_order: int) -> None:
        provider_id = _normalize_provider_id(getattr(provider, "provider_id", ""))
        if provider_id in registered:
            raise ValueError(f"Tool provider {provider_id!r} is already registered.")
        provider_config = settings.tool_catalog.provider_config_for(provider_id)
        if provider_config is not None and not provider_config.enabled:
            return
        order = provider_config.order if provider_config is not None else None
        registered[provider_id] = (default_order if order is None else order, provider)

    for entry in _TOOL_PROVIDER_FACTORY_REGISTRY.entries():
        if not provider_enabled(entry.provider_id):
            continue
        provider = entry.factory(context)
        returned_provider_id = _normalize_provider_id(getattr(provider, "provider_id", ""))
        if returned_provider_id != entry.provider_id:
            raise ValueError(
                f"Tool provider factory {entry.provider_id!r} returned provider "
                f"{returned_provider_id!r}."
            )
        register(provider, default_order=entry.default_order)

    explicit_index = 0
    for provider in explicit_provider_list:
        register(provider, default_order=200 + explicit_index)
        explicit_index += 1

    for provider_id, factory in explicit_factory_mapping.items():
        normalized_provider_id = _normalize_provider_id(provider_id)
        provider_config = settings.tool_catalog.provider_config_for(normalized_provider_id)
        if provider_config is not None and not provider_config.enabled:
            continue
        provider = factory(context)
        returned_provider_id = _normalize_provider_id(getattr(provider, "provider_id", ""))
        if returned_provider_id != normalized_provider_id:
            raise ValueError(
                f"Tool provider factory {normalized_provider_id!r} returned provider "
                f"{returned_provider_id!r}."
            )
        register(provider, default_order=200 + explicit_index)
        explicit_index += 1

    return tuple(
        provider
        for _provider_id, (_order, provider) in sorted(
            registered.items(),
            key=lambda item: (item[1][0], item[0]),
        )
    )


def _merge_tool_provider_manifests(
    providers: Iterable[ToolProvider],
    *,
    provider_metadata_overlay_for: Callable[[str], Mapping[str, Any]],
    provider_overrides_for: Callable[[str], Iterable[str]],
    metadata_overlay_for: Callable[[str], Mapping[str, Any]],
) -> dict[str, ToolManifest]:
    manifests: dict[str, ToolManifest] = {}
    for provider in providers:
        provider_id = _normalize_provider_id(provider.provider_id)
        provider_overlay = provider_metadata_overlay_for(provider_id)
        provider_overrides = set(provider_overrides_for(provider_id))
        for manifest in provider.tool_manifests():
            provider_manifest = manifest.with_overlay(provider_overlay)
            existing = manifests.get(provider_manifest.name)
            if (
                existing is not None
                and existing.provider_id != provider_manifest.provider_id
                and provider_manifest.name not in provider_overrides
            ):
                raise ValueError(
                    f"Tool provider {provider_id!r} cannot override tool "
                    f"{provider_manifest.name!r} from provider {existing.provider_id!r} "
                    "without declaring it in overrides."
                )
            manifests[provider_manifest.name] = provider_manifest.with_overlay(
                metadata_overlay_for(provider_manifest.name)
            )
    return manifests


def _normalize_provider_id(provider_id: object) -> str:
    normalized = str(provider_id or "").strip()
    if not _PROVIDER_ID_PATTERN.fullmatch(normalized):
        raise ValueError(
            f"Tool provider id must match {_PROVIDER_ID_PATTERN.pattern!r}; got {provider_id!r}."
        )
    return normalized


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


def _build_builtin_tool_provider(context: ToolProviderFactoryContext) -> ToolProvider:
    return StaticToolProvider(
        provider_id="builtin",
        tools=tuple(
            get_default_tools(
                context.settings,
                store=context.store,
                checkpointer=context.checkpointer,
                artifact_metadata_repository=context.artifact_metadata_repository,
            )
        ),
    )


def _build_skill_tool_provider(context: ToolProviderFactoryContext) -> ToolProvider:
    return StaticToolProvider(
        provider_id="skill",
        tools=tuple(
            _build_skill_tools(
                settings=context.settings,
                skill_registry=context.skill_registry,
            )
        ),
    )


_TOOL_PROVIDER_FACTORY_REGISTRY = ToolProviderFactoryRegistry()
_TOOL_PROVIDER_FACTORY_REGISTRY.register(
    "builtin",
    _build_builtin_tool_provider,
    default_order=0,
)
_TOOL_PROVIDER_FACTORY_REGISTRY.register(
    "skill",
    _build_skill_tool_provider,
    default_order=100,
)
