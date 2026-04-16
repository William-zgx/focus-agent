from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain.tools import tool

from ..config import Settings
from ..skills import SkillRegistry
from ..skills.registry import render_skill_view_json, render_skills_list_json
from .default_tools import get_default_tools


@dataclass(slots=True)
class ToolRegistry:
    tools: tuple[Any, ...]

    @property
    def by_name(self) -> dict[str, Any]:
        return {tool_.name: tool_ for tool_ in self.tools}


def build_tool_registry(*, settings: Settings, skill_registry: SkillRegistry) -> ToolRegistry:
    default_tools = {tool_.name: tool_ for tool_ in get_default_tools(settings)}
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
    skills_list.metadata = {"display_name": settings.tool_catalog.skills_list.label}
    skill_view.description = settings.tool_catalog.skill_view.description
    skill_view.metadata = {"display_name": settings.tool_catalog.skill_view.label}

    tools: list[Any] = []
    if settings.tool_catalog.skills_list.enabled:
        tools.append(skills_list)
    if settings.tool_catalog.skill_view.enabled:
        tools.append(skill_view)
    return tools
