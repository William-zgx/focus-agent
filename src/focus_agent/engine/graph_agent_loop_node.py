from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from langchain.messages import AIMessage, SystemMessage
from langgraph.runtime import Runtime

from ..agent_delegation import build_failure_records, build_review_queue
from ..capabilities import ToolRegistry
from ..capabilities.tool_router import build_tool_route_plan, infer_tool_router_role
from ..config import Settings
from ..core.context_policy import apply_prompt_budget_guard
from ..core.request_context import RequestContext
from ..core.state import AgentState, append_agent_state_record
from ..core.types import Plan
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
        available_tools = _tools_for_policy(tool_policy, all_tools, latest_user)
        tool_route_plan = None
        if settings.agent_tool_router_enabled:
            router_role = infer_tool_router_role(state.get("role_route_plan"))
            tool_route_plan = build_tool_route_plan(
                tool_registry=tool_registry,
                role=router_role,
                tool_policy=tool_policy,
                available_tool_names=[str(getattr(tool, "name", "")) for tool in available_tools],
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
        elif tool_policy == "live_web_research" and _live_web_research_should_start_with_search(
            latest_user,
            state_messages,
            available_tools,
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
        elif tool_policy == "workspace_lookup" and _workspace_lookup_should_start_with_search(
            latest_user,
            state_messages,
            available_tools,
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


__all__ = ["make_agent_loop_node"]
