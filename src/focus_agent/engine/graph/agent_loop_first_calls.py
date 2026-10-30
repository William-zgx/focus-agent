"""Deterministic first tool calls the agent loop issues without asking the model."""

from __future__ import annotations

from typing import Any

from langchain.messages import AIMessage

from ...capabilities.tool_router import ToolIntentPlan
from .agent_loop_helpers import (
    _has_tool_named,
    _latest_tool_result_content,
    _latest_turn_has_tool_result,
)
from .agent_loop_skill_helpers import skill_install_args_from_search_result
from .agent_loop_support import _web_fetch_args
from .policy import (
    _skill_install_name_from_text,
    _skill_view_name_from_text,
    _temporal_live_web_search_args,
)
from .policy_intent_parsing import _workspace_search_query
from .policy_temporal import search_time_range
from .policy_tools import _workspace_lookup_should_start_with_search


def _tool_call_message(call_id: str, name: str, args: dict[str, Any]) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"id": call_id, "name": name, "args": args}])


def anchor_planned_web_search_args(
    plan: ToolIntentPlan,
    *,
    tool_intent_text: str,
    current_utc_time_result: str,
    all_tools: list[Any],
) -> ToolIntentPlan:
    """Pin the planned web_search query (and time_range) to the verified UTC time."""

    if not (
        plan.policy == "live_web_research"
        and plan.preferred_first_tool == "web_search"
        and current_utc_time_result
    ):
        return plan
    anchored_args = _temporal_live_web_search_args(
        plan.preferred_first_args,
        fallback_query=tool_intent_text,
        current_utc_time=current_utc_time_result,
    )
    search_tool = next(
        (tool for tool in all_tools if getattr(tool, "name", "") == "web_search"), None
    )
    search_parameters = getattr(search_tool, "args", {})
    if (
        isinstance(search_parameters, dict)
        and "time_range" in search_parameters
        and (time_range := search_time_range(tool_intent_text))
    ):
        anchored_args.setdefault("time_range", time_range)
    if anchored_args and anchored_args != plan.preferred_first_args:
        return plan.model_copy(update={"preferred_first_args": anchored_args})
    return plan


def temporal_anchor_call(
    *,
    tool_policy: str,
    temporal_anchor_required: bool,
    available_tools: list[Any],
    state_messages: list[Any],
    call_index: int,
) -> AIMessage | None:
    """Force ``current_utc_time`` before a time-sensitive live-web turn."""

    if (
        tool_policy == "live_web_research"
        and temporal_anchor_required
        and _has_tool_named(available_tools, "current_utc_time")
        and not _latest_turn_has_tool_result(state_messages, "current_utc_time")
    ):
        return _tool_call_message(f"current-utc-time-{call_index}", "current_utc_time", {})
    return None


def planned_web_fetch_call(
    *,
    tool_policy: str,
    tool_intent_plan: ToolIntentPlan,
    tool_intent_text: str,
    available_tools: list[Any],
    state_messages: list[Any],
    call_index: int,
) -> AIMessage | None:
    """Fetch the URL the user named before anything else."""

    if (
        tool_policy == "live_web_research"
        and tool_intent_plan.preferred_first_tool == "web_fetch"
        and _has_tool_named(available_tools, "web_fetch")
        and not _latest_turn_has_tool_result(state_messages, "web_fetch")
    ):
        return _tool_call_message(
            f"live-web-fetch-{call_index}",
            "web_fetch",
            _web_fetch_args(tool_intent_plan.preferred_first_args, tool_intent_text),
        )
    return None


def planned_web_search_call(
    *, tool_intent_plan: ToolIntentPlan, tool_intent_text: str, call_index: int
) -> AIMessage:
    """Deterministic search used when the model skips the planned web_search."""

    return _tool_call_message(
        f"live-web-search-{call_index}",
        "web_search",
        tool_intent_plan.preferred_first_args or {"query": tool_intent_text},
    )


def skill_or_workspace_first_call(
    *,
    tool_policy: str,
    tool_intent_plan: ToolIntentPlan,
    tool_intent_text: str,
    available_tools: list[Any],
    state_messages: list[Any],
    tool_exposure: Any,
    call_index: int,
) -> AIMessage | None:
    """Skill discovery/install/view and workspace search calls, in priority order."""

    plan = tool_intent_plan
    args = plan.preferred_first_args

    def available(name: str) -> bool:
        return _has_tool_named(available_tools, name)

    def done(name: str) -> bool:
        return _latest_turn_has_tool_result(state_messages, name)

    if (
        tool_policy in {"workspace_lookup", "execution"}
        and plan.preferred_first_tool == "skills_search"
        and available("skills_search")
        and not done("skills_search")
    ):
        return _tool_call_message(
            f"skills-search-{call_index}",
            "skills_search",
            args or {"query": tool_intent_text},
        )
    if (
        tool_policy == "execution"
        and "skill_install_intent" in plan.reason_codes
        and available("skill_install")
        and done("skills_search")
        and not done("skill_install")
        and (
            install_args := skill_install_args_from_search_result(
                tool_intent_text,
                state_messages,
                latest_tool_result_content=_latest_tool_result_content,
                skill_install_name_from_text=_skill_install_name_from_text,
            )
        )
    ):
        return _tool_call_message(f"skill-install-{call_index}", "skill_install", install_args)
    if (
        tool_policy == "execution"
        and plan.preferred_first_tool == "skill_install"
        and available("skill_install")
        and not done("skill_install")
        and args.get("skill_id")
    ):
        return _tool_call_message(f"skill-install-{call_index}", "skill_install", args)
    if (
        tool_policy == "workspace_lookup"
        and plan.preferred_first_tool == "skill_view"
        and available("skill_view")
        and not done("skill_view")
        and args.get("name")
    ):
        return _tool_call_message(f"skill-view-{call_index}", "skill_view", args)
    if (
        tool_policy == "workspace_lookup"
        and "skill_view" in tool_intent_text.lower()
        and available("skill_view")
        and done("skills_search")
        and not done("skill_view")
        and (skill_view_name := _skill_view_name_from_text(tool_intent_text))
    ):
        return _tool_call_message(
            f"skill-view-{call_index}", "skill_view", {"name": skill_view_name}
        )
    if tool_policy == "workspace_lookup" and _workspace_lookup_should_start_with_search(
        tool_intent_text,
        state_messages,
        available_tools,
        exposure=tool_exposure,
    ):
        return _tool_call_message(
            f"workspace-search-{call_index}",
            "search_code",
            args or {"query": _workspace_search_query(tool_intent_text)},
        )
    return None
