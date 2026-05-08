from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langchain.messages import HumanMessage, ToolMessage
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from ..capabilities.default_tool_modules.memory import authorize_memory_tool_args
from ..capabilities.tool_runtime import (
    ToolExecutionInput,
    ToolResultCacheStore,
    build_cache_scope_key,
    build_tool_approval_interrupt_payload,
    build_tool_error_message,
    execute_tool_calls,
    is_tool_approval_approved,
    tool_approval_response_error,
)
from ..core.request_context import RequestContext
from ..core.state import AgentState, append_agent_state_record
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
        updates: dict[str, Any] = {}
        route_plan = _route_plan_mapping(state.get("tool_route_plan"))
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
            authorized_args, authorization_error = authorize_memory_tool_args(
                tool_name,
                tool_args,
                runtime.context,
            )
            if authorization_error is not None:
                messages_by_index[index] = build_tool_error_message(
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    args=tool_args,
                    error=authorization_error,
                    runtime_info={"memory_context_authorization_failed": True},
                )
                continue
            tool_args = authorized_args or tool_args
            tool = tools_by_name.get(tool_name)
            if tool is None:
                messages_by_index[index] = build_tool_error_message(
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    args=tool_args,
                    error=f"Unknown tool: {tool_name}",
                )
                continue
            if _forbidden_by_route_plan(route_plan, tool_name):
                messages_by_index[index] = build_tool_error_message(
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    args=tool_args,
                    error=f"Forbidden tool by Tool Router policy: {tool_name}",
                    runtime_info={"forbidden_by_tool_router": True},
                )
                continue
            runtime_meta = tool_runtime_by_name.get(tool_name)
            if runtime_meta is None:
                messages_by_index[index] = build_tool_error_message(
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    args=tool_args,
                    error=f"Tool runtime metadata is missing: {tool_name}",
                    runtime_info={"missing_tool_runtime_metadata": True},
                )
                continue
            execution_input = ToolExecutionInput(
                index=index,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                args=tool_args,
                tool=tool,
                runtime=runtime_meta,
            )
            if runtime_meta.requires_approval:
                approval_payload = build_tool_approval_interrupt_payload(execution_input)
                approval_response = interrupt(approval_payload)
                approval_error = tool_approval_response_error(
                    approval_response,
                    interrupt_id=str(approval_payload.get("interrupt_id") or ""),
                    tool_call_id=tool_call_id,
                )
                approved = is_tool_approval_approved(
                    approval_response,
                    interrupt_id=str(approval_payload.get("interrupt_id") or ""),
                    tool_call_id=tool_call_id,
                )
                append_agent_state_record(
                    updates,
                    "tool_approval_decision",
                    {
                        **approval_payload,
                        "approved": approved,
                        "approval_error": approval_error,
                        "decision": "approved" if approved else "denied",
                    },
                    source=f"tool_executor:{tool_call_id}",
                    metadata={
                        "interrupt_id": str(approval_payload.get("interrupt_id") or ""),
                        "tool_call_id": tool_call_id,
                    },
                )
                if not approved:
                    error = approval_error or f"Tool execution denied by approval response: {tool_name}"
                    messages_by_index[index] = build_tool_error_message(
                        tool_call_id=tool_call_id,
                        tool_name=tool_name,
                        args=dict(approval_payload.get("redacted_args") or {}),
                        error=error,
                        runtime_info={
                            "tool_approval_denied": True,
                            "tool_approval_invalid": approval_error is not None,
                            "requires_approval": True,
                            "risk_level": runtime_meta.risk_level or "low",
                        },
                    )
                    continue
            execution_inputs.append(execution_input)
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
        updates["messages"] = result_messages
        return updates

    return tool_executor


def _route_plan_mapping(route_plan: Any) -> Mapping[str, Any] | None:
    if isinstance(route_plan, Mapping):
        return route_plan
    model_dump = getattr(route_plan, "model_dump", None)
    if not callable(model_dump):
        return None
    dumped = model_dump(mode="json")
    return dumped if isinstance(dumped, Mapping) else None


def _forbidden_by_route_plan(
    route_plan: Mapping[str, Any] | None,
    tool_name: str,
) -> bool:
    if not route_plan or not bool(route_plan.get("enforce", True)):
        return False
    allowed_tools = {str(name) for name in route_plan.get("allowed_tools") or []}
    denied_tools = {str(name) for name in route_plan.get("denied_tools") or []}
    return tool_name in denied_tools or tool_name not in allowed_tools


__all__ = ["make_tool_executor_node"]
