from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from typing import Any

from langchain.messages import AIMessage, SystemMessage
from langgraph.runtime import Runtime

from ..agent_roles import AgentRole
from ..agent_delegation import build_failure_records, build_review_queue
from ..capabilities import ToolRegistry
from ..capabilities.tool_router import build_tool_route_plan, infer_tool_router_role
from ..config import Settings
from ..core.context_policy import apply_prompt_budget_guard
from ..core.request_context import RequestContext
from ..core.state import AgentState, append_agent_state_record
from ..core.types import Plan
from . import graph_tool_policy as _graph_tool_policy
from .graph_plan_nodes import _format_plan_block
from .graph_turn_helpers import (
    _TOOL_EXHAUSTION_NOTE,
    _classify_turn_tool_policy,
    _context_budget_from_state,
    _ensure_reasoning_content_for_tool_call_history,
    _invoke_with_tool_result_fallback,
    _known_tool_names,
    _latest_human_message_text,
    _latest_turn_messages,
    _live_web_research_should_start_with_search,
    _looks_like_textual_tool_call_artifact,
    _messages_for_model,
    _repair_and_dedupe_tool_calls,
    _repair_textual_tool_call_response,
    _repair_tool_free_answer_response,
    _should_force_tool_free_answer,
    _tool_policy_note,
    _tools_for_policy,
    _workspace_lookup_should_start_with_search,
    _workspace_search_query,
)


def make_agent_loop_node(
    *,
    settings: Settings,
    tools: Sequence[Any],
    tool_registry: ToolRegistry,
    model_for: Callable[[str, str], Any],
    model_with_tools_for: Callable[[str, str, list[Any] | None], Any],
) -> Any:
    all_tools = list(tools)

    def agent_loop(
        state: AgentState,
        runtime: Runtime[RequestContext],
    ) -> dict[str, Any]:
        del runtime
        state_messages = list(state.get("messages", []) or [])
        messages = _messages_for_model(state)
        fallback_messages = _latest_turn_messages(state_messages or messages)
        selected_model = str(state.get("selected_model") or settings.model)
        selected_thinking_mode = str(state.get("selected_thinking_mode") or "")
        assembled = state.get("assembled_context", "")
        latest_user = _latest_human_message_text(state_messages)
        if not latest_user:
            latest_user = _latest_human_message_text(messages) or str(state.get("task_brief") or "")
        context_budget = _context_budget_from_state(state)
        tool_policy = _classify_turn_tool_policy(latest_user)
        tool_exposure = _classify_turn_tool_exposure_if_available(
            latest_user,
            tool_policy=tool_policy,
        )
        available_tools = _tools_for_policy_compat(
            tool_policy,
            all_tools,
            latest_user,
            exposure=tool_exposure,
        )
        tool_route_plan = None
        if settings.agent_tool_router_enabled:
            router_role = infer_tool_router_role(
                state.get("role_route_plan"),
                fallback=_tool_router_fallback_role(tool_policy, tool_exposure),
            )
            tool_route_plan = build_tool_route_plan(
                tool_registry=tool_registry,
                role=router_role,
                tool_policy=tool_policy,
                available_tool_names=_registered_tool_names(tool_registry, all_tools),
                exposed_tool_names=[str(getattr(tool, "name", "")) for tool in available_tools],
                confidence=getattr(tool_exposure, "confidence", None),
                reason_codes=getattr(tool_exposure, "reason_codes", None),
                enforce=bool(settings.agent_tool_router_enforce),
            )
            if settings.agent_tool_router_enforce:
                allowed = set(tool_route_plan.allowed_tools)
                available_tools = [
                    tool for tool in available_tools if str(getattr(tool, "name", "")) in allowed
                ]
        known_names = _known_tool_names(available_tools)
        tool_protocol_repair_count = 0
        tool_protocol_repair_reason = ""
        policy_note = _tool_policy_note(tool_policy)
        plan = state.get("plan")
        if isinstance(plan, Plan) and plan.steps:
            plan_block = _format_plan_block(plan, state.get("current_step_id", ""))
            if plan_block and plan_block not in assembled:
                assembled = f"{assembled}\n\n{plan_block}".strip()
        prompt_messages = [SystemMessage(content=assembled), *messages]
        if policy_note:
            prompt_messages = [
                prompt_messages[0],
                SystemMessage(content=policy_note),
                *prompt_messages[1:],
            ]
        prompt_messages = apply_prompt_budget_guard(prompt_messages, budget=context_budget)
        prompt_messages = _ensure_reasoning_content_for_tool_call_history(
            prompt_messages,
            model_id=selected_model,
            thinking_mode=selected_thinking_mode,
            settings=settings,
        )
        if _should_force_tool_free_answer(state_messages):
            forced_prompt = apply_prompt_budget_guard(
                [
                    prompt_messages[0],
                    SystemMessage(content=_TOOL_EXHAUSTION_NOTE),
                    *prompt_messages[1:],
                ],
                budget=context_budget,
            )
            forced_prompt = _ensure_reasoning_content_for_tool_call_history(
                forced_prompt,
                model_id=selected_model,
                thinking_mode=selected_thinking_mode,
                settings=settings,
            )
            response = _invoke_with_tool_result_fallback(
                model_for(selected_model, selected_thinking_mode),
                forced_prompt,
                fallback_messages=fallback_messages,
                known_tool_names=known_names,
            )
            if _looks_like_textual_tool_call_artifact(response, known_tool_names=known_names):
                tool_protocol_repair_count += 1
                tool_protocol_repair_reason = "textual_tool_marker"
            response = _repair_tool_free_answer_response(
                response=response,
                prompt_messages=prompt_messages,
                fallback_messages=fallback_messages,
                context_budget=context_budget,
                selected_model=selected_model,
                selected_thinking_mode=selected_thinking_mode,
                model_for=model_for,
            )
        elif tool_policy == "live_web_research" and _live_web_research_should_start_with_search_compat(
            latest_user,
            state_messages,
            available_tools,
            exposure=tool_exposure,
        ):
            response = AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": f"live-web-search-{state.get('llm_calls', 0) + 1}",
                        "name": "web_search",
                        "args": {"query": latest_user},
                    }
                ],
            )
        elif tool_policy == "workspace_lookup" and _workspace_lookup_should_start_with_search_compat(
            latest_user,
            state_messages,
            available_tools,
            exposure=tool_exposure,
        ):
            response = AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": f"workspace-search-{state.get('llm_calls', 0) + 1}",
                        "name": "search_code",
                        "args": {"query": _workspace_search_query(latest_user)},
                    }
                ],
            )
        elif not available_tools:
            response = _invoke_with_tool_result_fallback(
                model_for(selected_model, selected_thinking_mode),
                prompt_messages,
                fallback_messages=fallback_messages,
                known_tool_names=known_names,
            )
            if _looks_like_textual_tool_call_artifact(response, known_tool_names=known_names):
                tool_protocol_repair_count += 1
                tool_protocol_repair_reason = "textual_tool_marker"
            response = _repair_tool_free_answer_response(
                response=response,
                prompt_messages=prompt_messages,
                fallback_messages=fallback_messages,
                context_budget=context_budget,
                selected_model=selected_model,
                selected_thinking_mode=selected_thinking_mode,
                model_for=model_for,
            )
        else:
            response = _invoke_with_tool_result_fallback(
                model_with_tools_for(selected_model, selected_thinking_mode, available_tools),
                prompt_messages,
                fallback_messages=fallback_messages,
                known_tool_names=known_names,
            )
            if _looks_like_textual_tool_call_artifact(response, known_tool_names=known_names):
                tool_protocol_repair_count += 1
                tool_protocol_repair_reason = "textual_tool_marker"
            response = _repair_textual_tool_call_response(
                response=response,
                prompt_messages=prompt_messages,
                fallback_messages=fallback_messages,
                context_budget=context_budget,
                selected_model=selected_model,
                selected_thinking_mode=selected_thinking_mode,
                available_tools=available_tools,
                model_for=model_for,
                model_with_tools_for=model_with_tools_for,
            )
        response = _repair_and_dedupe_tool_calls(response)
        updates: dict[str, Any] = {
            "messages": [response],
            "llm_calls": state.get("llm_calls", 0) + 1,
        }
        if tool_route_plan is not None:
            dumped = tool_route_plan.model_dump(mode="json")
            append_agent_state_record(
                updates,
                "tool_route_plan",
                dumped,
                source="agent_loop",
            )
            plan_meta = {
                **(state.get("plan_meta") or {}),
                "tool_route_plan": dumped,
            }
            if settings.agent_self_repair_enabled:
                failures = [
                    item.model_dump(mode="json")
                    for item in build_failure_records(
                        delegation_plan=state.get("agent_delegation_plan"),
                        tool_route_plan=dumped,
                        model_route_decision=state.get("model_route_decision"),
                    )
                ]
                append_agent_state_record(
                    updates,
                    "agent_failure_records",
                    failures,
                    source="agent_loop",
                )
                plan_meta["agent_failure_records"] = failures
            if settings.agent_review_queue_enabled:
                review_items = [
                    item.model_dump(mode="json")
                    for item in build_review_queue(
                        settings=settings,
                        memory_curator_decision=state.get("memory_curator_decision"),
                        tool_route_plan=dumped,
                        model_route_decision=state.get("model_route_decision"),
                        agent_failure_records=updates.get("agent_failure_records")
                        or state.get("agent_failure_records")
                        or [],
                    )
                ]
                append_agent_state_record(
                    updates,
                    "agent_review_queue",
                    review_items,
                    source="agent_loop",
                )
                plan_meta["agent_review_queue"] = review_items
            if updates.get("governance_records"):
                plan_meta["governance_records"] = [
                    *list(plan_meta.get("governance_records") or []),
                    *list(updates.get("governance_records") or []),
                ]
            updates["plan_meta"] = plan_meta
        if tool_protocol_repair_count:
            current_plan_meta = updates.get("plan_meta") or state.get("plan_meta") or {}
            plan_meta = {
                **current_plan_meta,
                "tool_protocol_repair_count": int(
                    current_plan_meta.get("tool_protocol_repair_count", 0)
                )
                + tool_protocol_repair_count,
                "tool_protocol_repair_reason": tool_protocol_repair_reason,
            }
            updates["plan_meta"] = plan_meta
        return updates

    return agent_loop


def _classify_turn_tool_exposure_if_available(
    latest_user: str,
    *,
    tool_policy: str,
) -> Any | None:
    classifier = getattr(_graph_tool_policy, "_classify_turn_tool_exposure", None)
    if not callable(classifier):
        return None
    if _accepts_keyword(classifier, "tool_policy"):
        return classifier(latest_user, tool_policy=tool_policy)
    if _accepts_keyword(classifier, "policy"):
        return classifier(latest_user, policy=tool_policy)
    if _requires_positional_count(classifier, 2):
        return classifier(latest_user, tool_policy)
    return classifier(latest_user)


def _tools_for_policy_compat(
    tool_policy: str,
    tools: list[Any],
    latest_user: str,
    *,
    exposure: Any | None,
) -> list[Any]:
    if exposure is not None and _accepts_keyword(_tools_for_policy, "exposure"):
        return _tools_for_policy(tool_policy, tools, latest_user, exposure=exposure)
    return _tools_for_policy(tool_policy, tools, latest_user)


def _live_web_research_should_start_with_search_compat(
    latest_user: str,
    state_messages: list[Any],
    available_tools: list[Any],
    *,
    exposure: Any | None,
) -> bool:
    if exposure is not None and _accepts_keyword(
        _live_web_research_should_start_with_search,
        "exposure",
    ):
        return _live_web_research_should_start_with_search(
            latest_user,
            state_messages,
            available_tools,
            exposure=exposure,
        )
    return _live_web_research_should_start_with_search(
        latest_user,
        state_messages,
        available_tools,
    )


def _workspace_lookup_should_start_with_search_compat(
    latest_user: str,
    state_messages: list[Any],
    available_tools: list[Any],
    *,
    exposure: Any | None,
) -> bool:
    if exposure is not None and _accepts_keyword(
        _workspace_lookup_should_start_with_search,
        "exposure",
    ):
        return _workspace_lookup_should_start_with_search(
            latest_user,
            state_messages,
            available_tools,
            exposure=exposure,
        )
    return _workspace_lookup_should_start_with_search(
        latest_user,
        state_messages,
        available_tools,
    )


def _tool_router_fallback_role(tool_policy: str, exposure: Any | None) -> AgentRole:
    if tool_policy == "live_web_research":
        return AgentRole.PLANNER
    if (
        tool_policy == "execution"
        and set(getattr(exposure, "allowed_toolsets", ()) or ()) == {"web", "workspace"}
    ):
        return AgentRole.PLANNER
    return AgentRole.EXECUTOR


def _registered_tool_names(tool_registry: ToolRegistry, tools: Sequence[Any]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()

    def add(raw_name: Any) -> None:
        name = str(raw_name or "").strip()
        if not name or name in seen:
            return
        seen.add(name)
        names.append(name)

    for tool in tuple(getattr(tool_registry, "tools", ()) or ()):
        add(getattr(tool, "name", ""))
    for mapping_name in ("by_name", "runtime_by_name", "manifest_by_name"):
        mapping = getattr(tool_registry, mapping_name, None)
        if isinstance(mapping, dict):
            for name in mapping:
                add(name)
    for tool in tools:
        add(getattr(tool, "name", ""))
    return names


def _accepts_keyword(function: Callable[..., Any], keyword: str) -> bool:
    try:
        signature = inspect.signature(function)
    except (TypeError, ValueError):
        return False
    return keyword in signature.parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )


def _requires_positional_count(function: Callable[..., Any], count: int) -> bool:
    try:
        signature = inspect.signature(function)
    except (TypeError, ValueError):
        return False
    required = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        and parameter.default is inspect.Parameter.empty
    ]
    return len(required) >= count


__all__ = ["make_agent_loop_node"]
