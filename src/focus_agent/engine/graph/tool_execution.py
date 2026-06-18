from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langchain.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from ...capabilities.default_tool_modules.memory import authorize_memory_tool_args
from ...capabilities.tool_runtime import (
    ToolExecutionInput,
    ToolResultCacheStore,
    build_cache_scope_key,
    build_tool_approval_interrupt_payload,
    build_tool_error_message,
    execute_tool_calls,
    is_tool_approval_approved,
    tool_approval_response_error,
)
from ...core.repo_call import has_repo_method
from ...core.request_context import RequestContext
from ...core.runtime_outcome import build_tool_outcomes_from_messages
from ...core.state import AgentState, append_agent_state_record
from ..graph_turn_helpers import (
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
    multi_agent_async_approval_enabled: bool = False,
    multi_agent_approval_timeout_seconds: float = 60.0,
    approval_queue: Any | None = None,
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
        turn_id = str(turn_index or 1)
        turn_scope_key = build_cache_scope_key(
            scope="turn",
            root_thread_id=root_thread_id,
            branch_id=branch_id,
            turn_id=str(turn_index or 1),
        )
        execution_inputs: list[ToolExecutionInput] = []
        execution_inputs_by_index: dict[int, ToolExecutionInput] = {}
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
        tool_call_counts: dict[str, int] = _tool_call_counts_since_latest_human(
            state.get("messages", [])[:-1]
        )
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
            tool_call_counts[tool_name] = tool_call_counts.get(tool_name, 0) + 1
            max_calls = getattr(runtime_meta, "max_calls_per_turn", None)
            if max_calls is not None and tool_call_counts[tool_name] > int(max_calls):
                messages_by_index[index] = build_tool_error_message(
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    args=tool_args,
                    error=f"Tool call budget exceeded for {tool_name}: max {int(max_calls)} per turn",
                    runtime_info={
                        "max_calls_per_turn_exceeded": True,
                        "max_calls_per_turn": int(max_calls),
                    },
                )
                continue
            validator = getattr(runtime_meta, "validator", None)
            if validator is not None:
                try:
                    validator(tool_args)
                except Exception as exc:  # noqa: BLE001
                    messages_by_index[index] = build_tool_error_message(
                        tool_call_id=tool_call_id,
                        tool_name=tool_name,
                        args=tool_args,
                        error=f"Invalid tool parameters for {tool_name}: {exc}",
                        runtime_info={"parameter_validation_error": True},
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
                if multi_agent_async_approval_enabled:
                    if has_repo_method(approval_queue, "submit_pending"):
                        approval_queue.submit_pending(
                            request_id=str(approval_payload.get("interrupt_id") or tool_call_id),
                            session_id=root_thread_id,
                            agent_id=f"tool_executor:{tool_call_id}",
                            tool_name=tool_name,
                            tool_args=dict(approval_payload.get("redacted_args") or {}),
                            risk_level=str(approval_payload.get("risk_level") or "low"),
                            timeout_seconds=multi_agent_approval_timeout_seconds,
                        )
                    append_agent_state_record(
                        updates,
                        "tool_approval_request",
                        {
                            **approval_payload,
                            "approval_status": "pending",
                            "policy_version": "multi_agent_async_approval.v1",
                        },
                        source=f"tool_executor:{tool_call_id}",
                        metadata={
                            "interrupt_id": str(approval_payload.get("interrupt_id") or ""),
                            "tool_call_id": tool_call_id,
                        },
                    )
                    messages_by_index[index] = build_tool_error_message(
                        tool_call_id=tool_call_id,
                        tool_name=tool_name,
                        args=dict(approval_payload.get("redacted_args") or {}),
                        error=("Tool execution is pending asynchronous approval and was not run."),
                        runtime_info={
                            "tool_approval_pending": True,
                            "requires_approval": True,
                            "risk_level": runtime_meta.risk_level or "low",
                        },
                    )
                    continue
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
                    error = (
                        approval_error or f"Tool execution denied by approval response: {tool_name}"
                    )
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
            execution_inputs_by_index[index] = execution_input
            cache_scope_keys[index] = build_cache_scope_key(
                scope=runtime_meta.cache_scope,
                root_thread_id=root_thread_id,
                branch_id=branch_id,
                turn_id=turn_id,
            )
        initial_results = execute_tool_calls(
            execution_inputs,
            context_budget=context_budget,
            cache_store=tool_result_cache,
            cache_scope_keys=cache_scope_keys,
            invalidation_scope_keys=invalidation_scope_keys,
            max_parallel_workers=max(1, int(max_parallel_workers or 1)),
        )
        for result in initial_results:
            messages_by_index[result.index] = result.message

        initial_messages = [messages_by_index[index] for index in sorted(messages_by_index)]
        tool_outcomes = build_tool_outcomes_from_messages(
            [last_message, *initial_messages],
            prior_outcomes=state.get("tool_outcomes") or [],
            turn_id=turn_id,
            human_turn_index=turn_index or 1,
        )
        retry_inputs = _retryable_failed_inputs(
            tool_outcomes,
            execution_inputs_by_index=execution_inputs_by_index,
        )
        if retry_inputs:
            append_agent_state_record(
                updates,
                "tool_retry",
                [
                    {
                        "tool_call_id": item.tool_call_id,
                        "tool_name": item.tool_name,
                        "attempt_index": 2,
                    }
                    for item in retry_inputs
                ],
                source="tool_executor",
                domain="observability",
            )
            retry_results = execute_tool_calls(
                retry_inputs,
                context_budget=context_budget,
                cache_store=tool_result_cache,
                cache_scope_keys=cache_scope_keys,
                invalidation_scope_keys=invalidation_scope_keys,
                max_parallel_workers=max(1, int(max_parallel_workers or 1)),
            )
            for result in retry_results:
                messages_by_index[result.index] = result.message
            retry_messages = [result.message for result in retry_results]
            tool_outcomes.extend(
                build_tool_outcomes_from_messages(
                    [last_message, *retry_messages],
                    prior_outcomes=[*(state.get("tool_outcomes") or []), *tool_outcomes],
                    turn_id=turn_id,
                    human_turn_index=turn_index or 1,
                )
            )

        result_messages = [messages_by_index[index] for index in sorted(messages_by_index)]
        updates["messages"] = result_messages
        if tool_outcomes:
            append_agent_state_record(
                updates,
                "tool_outcomes",
                tool_outcomes,
                source="tool_executor",
                domain="observability",
            )
        return updates

    return tool_executor


def _retryable_failed_inputs(
    outcomes: list[dict[str, Any]],
    *,
    execution_inputs_by_index: Mapping[int, ToolExecutionInput],
) -> list[ToolExecutionInput]:
    retry_call_ids = {
        str(outcome.get("tool_call_id") or "")
        for outcome in outcomes
        if str(outcome.get("status") or "") == "failed"
        and bool(outcome.get("retryable"))
        and int(outcome.get("attempt_index") or 1) < int(outcome.get("max_attempts") or 1)
    }
    if not retry_call_ids:
        return []
    retry_inputs: list[ToolExecutionInput] = []
    for item in execution_inputs_by_index.values():
        if item.tool_call_id not in retry_call_ids:
            continue
        if item.runtime.side_effect and not _retryable_side_effect_allowed(item):
            continue
        retry_inputs.append(item)
    return retry_inputs


def _retryable_side_effect_allowed(item: ToolExecutionInput) -> bool:
    if item.tool_name not in {"run_workspace_command", "run_skill_entrypoint"}:
        return False
    if str(item.runtime.side_effect_kind or "") != "workspace_command":
        return False
    return bool(item.runtime.requires_approval and getattr(item.runtime, "retry_safe", False))


def _tool_call_counts_since_latest_human(messages: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for message in reversed(messages or []):
        if isinstance(message, HumanMessage):
            break
        if not isinstance(message, AIMessage):
            continue
        for call in getattr(message, "tool_calls", None) or ():
            if not isinstance(call, Mapping):
                continue
            tool_name = str(call.get("name") or "").strip()
            if tool_name:
                counts[tool_name] = counts.get(tool_name, 0) + 1
    return counts


def _route_plan_mapping(route_plan: Any) -> Mapping[str, Any] | None:
    if isinstance(route_plan, Mapping):
        return route_plan
    if not has_repo_method(route_plan, "model_dump"):
        return None
    dumped = route_plan.model_dump(mode="json")
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
