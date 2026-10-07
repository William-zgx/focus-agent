"""Tool filtering and first-tool selection for a classified turn policy."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from langchain.messages import ToolMessage

from ...agent_roles import AgentRole
from ...capabilities.tool_registry import ToolRuntimeMeta
from ...capabilities.tool_router import CapabilityPolicyEngine
from .policy_intent_parsing import _ToolPolicy
from .policy_markers import (
    _CODE_SEARCH_TOOL_INTENT_MARKERS,
    _FILE_BROWSE_INTENT_MARKERS,
    _LIVE_WEB_SEARCH_FIRST_MARKERS,
    _contains_any,
)

if TYPE_CHECKING:
    from .policy import TurnToolExposure


def _tools_for_policy(
    policy: _ToolPolicy,
    tools: list[Any],
    latest_user: str = "",
    *,
    role: AgentRole | str | None = None,
    exposure: TurnToolExposure | None = None,
) -> list[Any]:
    effective_policy = exposure.policy if exposure is not None else policy
    policy_engine = CapabilityPolicyEngine()
    roles = _roles_for_policy(effective_policy, role=role, exposure=exposure)
    candidates = [
        tool
        for tool in tools
        if any(
            policy_engine.tool_allowed(tool, role=effective_role, tool_policy=effective_policy)[0]
            for effective_role in roles
        )
    ]
    if exposure is not None:
        candidates = _filter_tools_by_exposure(candidates, exposure)
    if effective_policy == "workspace_lookup":
        normalized = " ".join(latest_user.strip().split())
        if _contains_any(normalized, _CODE_SEARCH_TOOL_INTENT_MARKERS) and not _contains_any(
            normalized, _FILE_BROWSE_INTENT_MARKERS
        ):
            focused = [
                tool
                for tool in candidates
                if "code_search" in _tool_runtime(tool).intent_tags or tool.name == "artifact_read"
            ]
            if focused:
                return focused
    return candidates


def _roles_for_policy(
    policy: _ToolPolicy,
    *,
    role: AgentRole | str | None,
    exposure: TurnToolExposure | None,
) -> tuple[AgentRole | str, ...]:
    if role is not None:
        return (role,)
    if exposure is not None and set(exposure.allowed_toolsets) == {"skill"}:
        return (AgentRole.SKILL_SCOUT, AgentRole.PLANNER)
    if (
        exposure is not None
        and policy == "execution"
        and set(exposure.allowed_toolsets) == {"web", "workspace"}
    ):
        return (AgentRole.PLANNER, AgentRole.EXECUTOR)
    return (_default_role_for_policy(policy),)


def _filter_tools_by_exposure(tools: list[Any], exposure: TurnToolExposure) -> list[Any]:
    allowed_toolsets = set(exposure.allowed_toolsets)
    hard_denied_toolsets = set(exposure.hard_denied_toolsets)
    filtered: list[Any] = []
    for tool in tools:
        runtime = _tool_runtime(tool)
        # Retrieved observations can be paged without exposing artifact-writing tools.
        if (
            (
                (exposure.policy == "workspace_lookup" and "workspace" in allowed_toolsets)
                or (exposure.policy == "live_web_research" and "web" in allowed_toolsets)
            )
            and tool.name == "artifact_read"
            and not runtime.side_effect
        ):
            filtered.append(tool)
            continue
        if runtime.toolset in hard_denied_toolsets:
            continue
        if allowed_toolsets and runtime.toolset not in allowed_toolsets:
            continue
        if exposure.policy == "execution" and allowed_toolsets and allowed_toolsets != {"skill"}:
            if runtime.side_effect or runtime.requires_workspace_write:
                continue
        filtered.append(tool)
    return filtered


def _tool_runtime(tool: Any) -> ToolRuntimeMeta:
    return ToolRuntimeMeta.from_tool(tool)


def _default_role_for_policy(policy: _ToolPolicy) -> AgentRole:
    if policy == "live_web_research":
        return AgentRole.PLANNER
    return AgentRole.EXECUTOR


def _workspace_lookup_should_start_with_search(
    text: str, messages: list[Any], tools: list[Any], exposure: TurnToolExposure | None = None
) -> bool:
    normalized = " ".join(text.strip().split())
    if not normalized:
        return False
    if any(isinstance(message, ToolMessage) for message in messages):
        return False
    if not any(str(getattr(tool, "name", "")) == "search_code" for tool in tools):
        return False
    if exposure is not None and exposure.preferred_first_tool is not None:
        return exposure.preferred_first_tool == "search_code"
    return _contains_any(normalized, _CODE_SEARCH_TOOL_INTENT_MARKERS) and not _contains_any(
        normalized,
        _FILE_BROWSE_INTENT_MARKERS,
    )


def _live_web_research_should_start_with_search(
    text: str, messages: list[Any], tools: list[Any], exposure: TurnToolExposure | None = None
) -> bool:
    normalized = " ".join(text.strip().split())
    if not normalized:
        return False
    if _has_non_temporal_anchor_tool_result(messages):
        return False
    if not any(str(getattr(tool, "name", "")) == "web_search" for tool in tools):
        return False
    if exposure is not None and exposure.preferred_first_tool is not None:
        return exposure.preferred_first_tool == "web_search"
    return _contains_any(normalized, _LIVE_WEB_SEARCH_FIRST_MARKERS)


def _has_non_temporal_anchor_tool_result(messages: list[Any]) -> bool:
    latest_human_index = -1
    for index, message in enumerate(messages):
        if getattr(message, "type", None) == "human":
            latest_human_index = index

    call_names_by_id: dict[str, str] = {}
    for message in messages[latest_human_index + 1 :]:
        for call in getattr(message, "tool_calls", None) or ():
            if not isinstance(call, Mapping):
                continue
            call_id = str(call.get("id") or "").strip()
            name = str(call.get("name") or "").strip()
            if call_id and name:
                call_names_by_id[call_id] = name
        if isinstance(message, ToolMessage):
            name = call_names_by_id.get(str(message.tool_call_id or "").strip())
            if name != "current_utc_time":
                return True
    return False


__all__ = [
    "_default_role_for_policy",
    "_filter_tools_by_exposure",
    "_has_non_temporal_anchor_tool_result",
    "_live_web_research_should_start_with_search",
    "_roles_for_policy",
    "_tool_runtime",
    "_tools_for_policy",
    "_workspace_lookup_should_start_with_search",
]
