from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from langchain.tools import tool

from ..config import Settings
from ..skills import SkillRegistry
from ..skills.registry import render_skill_view_json, render_skills_list_json
from .default_tools import get_default_tools

ToolArgValidator = Callable[[Mapping[str, Any]], None]
ToolFallbackHandler = Callable[[Exception, Mapping[str, Any]], Any]


@dataclass(frozen=True, slots=True)
class ToolRuntimeMeta:
    side_effect: bool = False
    parallel_safe: bool = False
    cacheable: bool = False
    cache_scope: str = "thread"
    fallback_group: str | None = None
    fallback_handler: ToolFallbackHandler | None = None
    max_observation_chars: int | None = None
    validator: ToolArgValidator | None = None

    @classmethod
    def from_tool(cls, tool_obj: Any) -> ToolRuntimeMeta:
        metadata = getattr(tool_obj, "metadata", None)
        if not isinstance(metadata, dict):
            return cls()
        return cls(
            side_effect=bool(metadata.get("side_effect", False)),
            parallel_safe=bool(metadata.get("parallel_safe", False)),
            cacheable=bool(metadata.get("cacheable", False)),
            cache_scope=str(metadata.get("cache_scope") or "thread"),
            fallback_group=(
                str(metadata["fallback_group"])
                if metadata.get("fallback_group")
                else None
            ),
            fallback_handler=metadata.get("fallback_handler"),
            max_observation_chars=(
                int(metadata["max_observation_chars"])
                if metadata.get("max_observation_chars") is not None
                else None
            ),
            validator=metadata.get("validator"),
        )


@dataclass(slots=True)
class ToolRegistry:
    tools: tuple[Any, ...]
    _by_name: dict[str, Any] = field(init=False, repr=False)
    _runtime_by_name: dict[str, ToolRuntimeMeta] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._by_name = {tool_.name: tool_ for tool_ in self.tools}
        self._runtime_by_name = {
            tool_.name: ToolRuntimeMeta.from_tool(tool_)
            for tool_ in self.tools
        }

    @property
    def by_name(self) -> dict[str, Any]:
        return self._by_name

    @property
    def runtime_by_name(self) -> dict[str, ToolRuntimeMeta]:
        return self._runtime_by_name


def build_tool_registry(
    *,
    settings: Settings,
    skill_registry: SkillRegistry,
    store=None,
    checkpointer=None,
) -> ToolRegistry:
    default_tools = {
        tool_.name: tool_
        for tool_ in get_default_tools(
            settings,
            store=store,
            checkpointer=checkpointer,
        )
    }
    skill_tools = {tool_.name: tool_ for tool_ in _build_skill_tools(settings=settings, skill_registry=skill_registry)}
    all_tools = {**default_tools, **skill_tools}
    return ToolRegistry(
        tools=tuple(
            all_tools[tool_name]
            for tool_name in settings.tool_catalog.section_names
            if tool_name in all_tools
        ),
    )


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
    }
    skill_view.description = settings.tool_catalog.skill_view.description
    skill_view.metadata = {
        "display_name": settings.tool_catalog.skill_view.label,
        "parallel_safe": True,
        "cacheable": True,
        "cache_scope": "thread",
        "max_observation_chars": 8000,
    }

    tools: list[Any] = []
    if settings.tool_catalog.skills_list.enabled:
        tools.append(skills_list)
    if settings.tool_catalog.skill_view.enabled:
        tools.append(skill_view)
    return tools
