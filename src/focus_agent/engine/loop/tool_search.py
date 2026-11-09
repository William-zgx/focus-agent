"""On-demand tool discovery and transcript-derived deferred tool loading."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from langchain.messages import AIMessage
from langchain_core.tools import StructuredTool
from langgraph.runtime import Runtime
from pydantic import BaseModel, Field

from ...capabilities.tool_manifest import ToolManifest, normalize_tool_metadata
from ...capabilities.tool_registry import ToolRegistry
from ...config import Settings
from ...core.request_context import RequestContext
from ...core.state import AgentState
from ..tools.execution import HarnessToolServices
from ..tools.messages import iter_tool_results, tool_message_failed
from .components import GraphComponents, make_graph_tool_executor
from .support import _filter_tools_by_agent_def, _resolve_agent_definition

TOOL_SEARCH_TOOL_NAME = "tool_search"
_LOADED_PREFIX = "Loaded tools:"
_SEARCH_TOOL_MARKER = "_focus_agent_deferred_tool_search"
_DESCRIPTION_LIMIT = 100
_EMPTY_QUERY_ERROR = "query must not be empty; use select:name_a,name_b or keywords"


class ToolSearchInput(BaseModel):
    query: str = Field(
        description="Exact names as select:name_a,name_b, or keywords for deferred tools."
    )
    max_results: int = Field(default=5, description="Maximum keyword results, clamped to 1-10.")


def tool_is_deferred(tool_obj: Any) -> bool:
    name = str(getattr(tool_obj, "name", "") or "").strip()
    metadata = getattr(tool_obj, "metadata", None)
    return bool(
        normalize_tool_metadata(
            name=name,
            metadata=metadata if isinstance(metadata, dict) else None,
        ).get("defer_loading", False)
    )


def _description(tool_obj: Any) -> str:
    text = " ".join(str(getattr(tool_obj, "description", "") or "").split())
    sentence = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    if len(sentence) <= _DESCRIPTION_LIMIT:
        return sentence
    return f"{sentence[: _DESCRIPTION_LIMIT - 1].rstrip()}…"


def _format_matches(matches: list[Any], *, unknown: list[str] | None = None) -> str:
    lines = [f"{_LOADED_PREFIX} {', '.join(tool.name for tool in matches)}"]
    lines.extend(f"- {tool.name}: {_description(tool)}" for tool in matches)
    lines.append("These tools are now loaded and can be called.")
    if unknown:
        lines.append(f"Unknown or unavailable tools: {', '.join(unknown)}")
    return "\n".join(lines)


def _no_matches(deferred_tools: list[Any], unknown: list[str] | None = None) -> str:
    lines = ["No deferred tools matched; nothing was loaded."]
    if unknown:
        lines.append(f"Unknown or unavailable tools: {', '.join(unknown)}")
    suggestions = ", ".join(tool.name for tool in deferred_tools[:5])
    if suggestions:
        lines.append(f"Available deferred tools include: {suggestions}")
    return "\n".join(lines)


def _keyword_matches(deferred_tools: list[Any], query: str, max_results: int) -> list[Any]:
    terms = tuple(dict.fromkeys(query.lower().split()))
    ranked: list[tuple[int, int, int, Any]] = []
    for index, tool_obj in enumerate(deferred_tools):
        name = str(tool_obj.name)
        metadata = normalize_tool_metadata(
            name=name,
            metadata=getattr(tool_obj, "metadata", None),
        )
        name_text = f"{name.lower()} {name.lower().replace('_', ' ')}"
        description = str(getattr(tool_obj, "description", "") or "").lower()
        tags = " ".join(
            [
                str(metadata.get("toolset") or ""),
                *(str(tag) for tag in metadata.get("intent_tags") or ()),
            ]
        ).lower()
        body_text = f"{description} {tags}"
        name_hits = sum(term in name_text for term in terms)
        body_hits = sum(term in body_text for term in terms)
        if name_hits or body_hits:
            ranked.append((-name_hits, -body_hits, index, tool_obj))
    ranked.sort(key=lambda item: item[:3])
    return [item[3] for item in ranked[:max_results]]


def build_tool_search_tool(deferred_tools: list[Any]) -> StructuredTool:
    tools = list(deferred_tools)
    by_name = {str(tool.name): tool for tool in tools}

    def _tool_search(query: str, max_results: int = 5) -> str:
        normalized = query.strip()
        if not normalized:
            raise ValueError(_EMPTY_QUERY_ERROR)
        limit = max(1, min(int(max_results), 10))
        if normalized.lower().startswith("select:"):
            requested = normalized.split(":", 1)[1]
            names = [name.strip() for name in requested.split(",") if name.strip()]
            if not names:
                raise ValueError("select: requires at least one tool name")
            unique_names = list(dict.fromkeys(names))
            matches = [by_name[name] for name in unique_names if name in by_name]
            unknown = [name for name in unique_names if name not in by_name]
            if not matches:
                return _no_matches(tools, unknown)
            return _format_matches(matches, unknown=unknown)
        matches = _keyword_matches(tools, normalized, limit)
        if not matches:
            return _no_matches(tools)
        return _format_matches(matches)

    tool_search = StructuredTool.from_function(
        func=_tool_search,
        name=TOOL_SEARCH_TOOL_NAME,
        description=(
            "Find and load deferred tools when a needed capability is listed under "
            "'Deferred tools' or is not in your available tools. Use select:name_a,name_b "
            "to load exact tools, or keywords to search names, descriptions and tags. "
            "Loaded tools can be called immediately and remain available on this branch."
        ),
        args_schema=ToolSearchInput,
    )
    tool_search.metadata = {
        "display_name": "Tool Search",
        "parallel_safe": True,
        "cacheable": False,
        "side_effect": False,
        "requires_approval": False,
        "risk_level": "low",
        "toolset": "meta",
        "intent_tags": ("tool_search", "tool_loading"),
        _SEARCH_TOOL_MARKER: True,
    }
    return tool_search


def deferred_tools_block(deferred_tools: list[Any]) -> str:
    if not deferred_tools:
        return ""
    lines = [
        "## Deferred tools",
        "These tools are deferred and may not be loaded yet. Before using one that is not "
        "in your available tools, call tool_search with select:<names> or keywords to load it.",
    ]
    lines.extend(f"- {tool.name}: {_description(tool)}" for tool in deferred_tools)
    return "\n".join(lines)


def loaded_deferred_tool_names(messages: list[Any], deferred_tools: list[Any]) -> set[str]:
    deferred_names = {str(tool.name) for tool in deferred_tools}
    loaded: set[str] = set()
    for message in messages:
        if isinstance(message, AIMessage):
            for call in getattr(message, "tool_calls", None) or ():
                name = str(call.get("name") or "").strip()
                if name in deferred_names:
                    loaded.add(name)
    for message, tool_name, _args in iter_tool_results(messages):
        if tool_name != TOOL_SEARCH_TOOL_NAME or tool_message_failed(message):
            continue
        content = getattr(message, "content", "")
        if not isinstance(content, str):
            continue
        first_line = content.splitlines()[0] if content else ""
        if not first_line.startswith(_LOADED_PREFIX):
            continue
        names = first_line[len(_LOADED_PREFIX) :].strip()
        loaded.update(name.strip() for name in names.split(",") if name.strip() in deferred_names)
    return loaded


def _is_our_search_tool(tool_obj: Any) -> bool:
    metadata = getattr(tool_obj, "metadata", None)
    return (
        str(getattr(tool_obj, "name", "") or "") == TOOL_SEARCH_TOOL_NAME
        and isinstance(metadata, dict)
        and metadata.get(_SEARCH_TOOL_MARKER) is True
    )


def _replace_tool_search(
    components: GraphComponents,
    deferred_tools: list[Any],
    *,
    keep_search: bool = False,
) -> GraphComponents:
    tools = list(components.tools)
    manifests = list(components.tool_registry.manifests)
    positions = [index for index, tool_obj in enumerate(tools) if _is_our_search_tool(tool_obj)]
    for index in reversed(positions):
        tools.pop(index)
        manifests.pop(index)
    if deferred_tools or keep_search:
        tool_search = build_tool_search_tool(deferred_tools)
        insert_at = positions[0] if positions else len(tools)
        tools.insert(insert_at, tool_search)
        manifests.insert(insert_at, ToolManifest.from_tool(tool_search))
    registry = ToolRegistry(tools=tuple(tools), manifests=tuple(manifests))
    return replace(components, tools=list(registry.tools), tool_registry=registry)


def with_tool_search(*, settings: Settings, components: GraphComponents) -> GraphComponents:
    if TOOL_SEARCH_TOOL_NAME in components.tool_registry.by_name and not any(
        _is_our_search_tool(tool_obj) for tool_obj in components.tools
    ):
        return components
    base = _replace_tool_search(components, [])
    if not settings.agent_deferred_tools_enabled:
        return base
    deferred = [tool_obj for tool_obj in base.tools if tool_is_deferred(tool_obj)]
    return _replace_tool_search(base, deferred)


def make_loop_tool_executor(
    *,
    settings: Settings,
    components: GraphComponents,
    approval_queue: Any | None,
    harness_services: HarnessToolServices | None,
    include_tool_invocation_context: bool = False,
    allow_approval_interrupts: bool = True,
    agent_definition_registry: Any | None = None,
) -> Any:
    factory_kwargs = {
        "settings": settings,
        "approval_queue": approval_queue,
        "harness_services": harness_services,
        "include_tool_invocation_context": include_tool_invocation_context,
        "allow_approval_interrupts": allow_approval_interrupts,
    }
    if not any(_is_our_search_tool(tool_obj) for tool_obj in components.tools):
        return make_graph_tool_executor(components=components, **factory_kwargs)

    executors: dict[tuple[str, ...], Any] = {}

    def tool_executor(state: AgentState, runtime: Runtime[RequestContext]) -> dict[str, Any]:
        agent_def, _agent_name = _resolve_agent_definition(agent_definition_registry, state)
        available = _filter_tools_by_agent_def(components.tools, agent_def)
        key = tuple(tool_obj.name for tool_obj in available)
        if key not in executors:
            registry = ToolRegistry(
                tools=tuple(available),
                manifests=tuple(
                    components.tool_registry.manifest_by_name[str(tool_obj.name)]
                    for tool_obj in available
                ),
            )
            available_components = replace(
                components,
                tools=list(registry.tools),
                tool_registry=registry,
            )
            deferred = [tool_obj for tool_obj in available if tool_is_deferred(tool_obj)]
            scoped = _replace_tool_search(
                available_components,
                deferred,
                keep_search=any(_is_our_search_tool(tool_obj) for tool_obj in available),
            )
            executors[key] = make_graph_tool_executor(components=scoped, **factory_kwargs)
        return executors[key](state, runtime)

    return tool_executor


__all__ = [
    "TOOL_SEARCH_TOOL_NAME",
    "build_tool_search_tool",
    "deferred_tools_block",
    "loaded_deferred_tool_names",
    "make_loop_tool_executor",
    "tool_is_deferred",
    "with_tool_search",
]
