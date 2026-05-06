from __future__ import annotations

from langgraph.config import get_stream_writer  # noqa: F401

from ..core.types import ContextBudget
from .tool_cache import ToolResultCacheStore, build_cache_scope_key, invalidate_after_side_effect
from .tool_execution import execute_single
from .tool_execution_types import (
    ToolExecutionInput,
    ToolExecutionResult,
    ToolParallelClassification,
    build_tool_approval_interrupt_payload,
    is_tool_approval_approved,
)
from .tool_invocation import ToolInvocationTimeoutError, ToolParameterValidationError
from .tool_messages import build_tool_error_message
from .tool_parallel import classify_tool_parallel_execution, run_parallel_batch

__all__ = [
    "ToolExecutionInput",
    "ToolExecutionResult",
    "ToolInvocationTimeoutError",
    "ToolParallelClassification",
    "ToolParameterValidationError",
    "ToolResultCacheStore",
    "build_cache_scope_key",
    "build_tool_approval_interrupt_payload",
    "build_tool_error_message",
    "classify_tool_parallel_execution",
    "execute_tool_calls",
    "is_tool_approval_approved",
]


def execute_tool_calls(
    tool_calls: list[ToolExecutionInput],
    *,
    context_budget: ContextBudget,
    cache_store: ToolResultCacheStore | None = None,
    cache_scope_keys: dict[int, str] | None = None,
    invalidation_scope_keys: list[str] | None = None,
    max_parallel_workers: int = 4,
) -> list[ToolExecutionResult]:
    pending_parallel: list[ToolExecutionInput] = []
    completed: list[ToolExecutionResult] = []

    for item in tool_calls:
        classification = classify_tool_parallel_execution(item.runtime)
        if classification.can_run_in_parallel:
            pending_parallel.append(item)
            continue
        if pending_parallel:
            completed.extend(
                run_parallel_batch(
                    pending_parallel,
                    context_budget=context_budget,
                    cache_store=cache_store,
                    cache_scope_keys=cache_scope_keys or {},
                    max_parallel_workers=max_parallel_workers,
                    execute_single=execute_single,
                )
            )
            pending_parallel = []
        completed.append(
            execute_single(
                item,
                context_budget=context_budget,
                cache_store=cache_store,
                cache_scope_key=(cache_scope_keys or {}).get(item.index),
                parallel_batch_size=None,
            )
        )
        if item.runtime.side_effect and completed[-1].message.status != "error":
            invalidate_after_side_effect(
                cache_store=cache_store,
                invalidation_scope_keys=invalidation_scope_keys or [],
            )

    if pending_parallel:
        completed.extend(
            run_parallel_batch(
                pending_parallel,
                context_budget=context_budget,
                cache_store=cache_store,
                cache_scope_keys=cache_scope_keys or {},
                max_parallel_workers=max_parallel_workers,
                execute_single=execute_single,
            )
        )

    completed.sort(key=lambda item: item.index)
    return completed
