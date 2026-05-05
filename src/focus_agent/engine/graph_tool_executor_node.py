from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langchain.messages import HumanMessage, ToolMessage
from langgraph.runtime import Runtime

from ..capabilities.tool_runtime import (
    ToolExecutionInput,
    ToolResultCacheStore,
    build_cache_scope_key,
    build_tool_error_message,
    execute_tool_calls,
)
from ..core.request_context import RequestContext
from ..core.state import AgentState
from .graph_turn_helpers import (
    _canonicalize_tool_call_args,
    _context_budget_from_state,
    _tool_call_signature,
)


def make_tool_executor_node(
    *,
    tools_by_name: Mapping[str, Any],
    tool_runtime_by_name: Mapping[str, Any],
    tool_result_cache: ToolResultCacheStore,
    max_parallel_workers: int = 4,
) -> Any:
    def tool_executor(
        state: AgentState,
        runtime: Runtime[RequestContext],
    ) -> dict[str, Any]:
        last_message = state["messages"][-1]
        context_budget = _context_budget_from_state(state)
        branch_meta = state.get("branch_meta") or {}
        branch_id = None
        if isinstance(branch_meta, dict):
            raw_branch_id = branch_meta.get("branch_id") or branch_meta.get("id")
            branch_id = str(raw_branch_id) if raw_branch_id else None
        root_thread_id = runtime.context.root_thread_id
        if runtime.context.branch_id and not branch_id:
            branch_id = runtime.context.branch_id
        turn_index = sum(
            1 for message in state.get("messages", []) if isinstance(message, HumanMessage)
        )
        turn_scope_key = build_cache_scope_key(
            scope="turn",
            root_thread_id=root_thread_id,
            branch_id=branch_id,
            turn_id=str(turn_index or 1),
        )
        execution_inputs: list[ToolExecutionInput] = []
        cache_scope_keys: dict[int, str] = {}
        invalidation_scope_keys = [
            turn_scope_key,
            build_cache_scope_key(
                scope="thread", root_thread_id=root_thread_id, branch_id=branch_id
            ),
            build_cache_scope_key(
                scope="branch", root_thread_id=root_thread_id, branch_id=branch_id
            ),
        ]
        messages_by_index: dict[int, ToolMessage] = {}
        seen_tool_call_signatures: set[str] = set()
        for index, tool_call in enumerate(getattr(last_message, "tool_calls", []) or []):
            tool_name = str(tool_call.get("name") or "").strip()
            tool_call_id = str(tool_call.get("id") or "").strip() or f"tool-call-{index + 1}"
            tool_args = _canonicalize_tool_call_args(tool_call.get("args"))
            if not tool_name:
                messages_by_index[index] = build_tool_error_message(
                    tool_call_id=tool_call_id,
                    tool_name="unknown_tool",
                    args=tool_args,
                    error="Malformed tool call: missing tool name",
                    runtime_info={"malformed_tool_call": True},
                )
                continue
            signature = _tool_call_signature({"name": tool_name, "args": tool_args})
            if signature in seen_tool_call_signatures:
                messages_by_index[index] = build_tool_error_message(
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    args=tool_args,
                    error=f"Duplicate tool call suppressed: {tool_name}",
                    runtime_info={"duplicate_tool_call_suppressed": True},
                )
                continue
            seen_tool_call_signatures.add(signature)
            route_plan = state.get("tool_route_plan") or {}
            denied_tools = (
                set(route_plan.get("denied_tools") or []) if isinstance(route_plan, dict) else set()
            )
            if tool_name in denied_tools and bool(route_plan.get("enforce", True)):
                messages_by_index[index] = build_tool_error_message(
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    args=tool_args,
                    error=f"Forbidden tool by Tool Router policy: {tool_name}",
                    runtime_info={"forbidden_by_tool_router": True},
                )
                continue
            tool = tools_by_name.get(tool_name)
            if tool is None:
                messages_by_index[index] = build_tool_error_message(
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    args=tool_args,
                    error=f"Unknown tool: {tool_name}",
                )
                continue
            runtime_meta = tool_runtime_by_name.get(tool_name)
            if runtime_meta is None:
                continue
            execution_inputs.append(
                ToolExecutionInput(
                    index=index,
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    args=tool_args,
                    tool=tool,
                    runtime=runtime_meta,
                )
            )
            cache_scope_keys[index] = build_cache_scope_key(
                scope=runtime_meta.cache_scope,
                root_thread_id=root_thread_id,
                branch_id=branch_id,
                turn_id=str(turn_index or 1),
            )
        for result in execute_tool_calls(
            execution_inputs,
            context_budget=context_budget,
            cache_store=tool_result_cache,
            cache_scope_keys=cache_scope_keys,
            invalidation_scope_keys=invalidation_scope_keys,
            max_parallel_workers=max(1, int(max_parallel_workers or 1)),
        ):
            messages_by_index[result.index] = result.message
        result_messages = [messages_by_index[index] for index in sorted(messages_by_index)]
        return {"messages": result_messages}

    return tool_executor


__all__ = ["make_tool_executor_node"]
