from __future__ import annotations

import atexit
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
import threading

from ..core.types import ContextBudget
from .tool_cache import ToolResultCacheStore, cache_key
from .tool_events import emit_runtime_tool_event
from .tool_execution_types import ToolExecutionInput, ToolExecutionResult, ToolParallelClassification
from .tool_messages import copy_result_for_tool_call
from .tool_registry import ToolRuntimeMeta


ExecuteSingle = Callable[
    [ToolExecutionInput, ContextBudget, ToolResultCacheStore | None, str | None, int | None],
    ToolExecutionResult,
]

_parallel_executor_lock = threading.Lock()
_parallel_executors: dict[int, ThreadPoolExecutor] = {}


def _parallel_executor(max_workers: int) -> ThreadPoolExecutor:
    workers = max(1, int(max_workers or 1))
    with _parallel_executor_lock:
        executor = _parallel_executors.get(workers)
        if executor is None:
            executor = ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix="focus-agent-tool",
            )
            _parallel_executors[workers] = executor
        return executor


def _shutdown_parallel_executors() -> None:
    for executor in list(_parallel_executors.values()):
        executor.shutdown(wait=False, cancel_futures=True)


atexit.register(_shutdown_parallel_executors)


def classify_tool_parallel_execution(runtime: ToolRuntimeMeta) -> ToolParallelClassification:
    if runtime.side_effect:
        kind = runtime.side_effect_kind or "side_effect"
        return ToolParallelClassification(
            mode="serialized_side_effect",
            reason=f"Tool has side effects ({kind}) and must be serialized.",
        )
    if runtime.parallel_safe:
        return ToolParallelClassification(
            mode="parallel_safe",
            reason="Tool metadata marks it parallel-safe and read-only.",
        )
    return ToolParallelClassification(
        mode="serialized_runtime",
        reason="Tool metadata does not mark it parallel-safe.",
    )


def run_parallel_batch(
    tool_calls: list[ToolExecutionInput],
    *,
    context_budget: ContextBudget,
    cache_store: ToolResultCacheStore | None,
    cache_scope_keys: dict[int, str],
    max_parallel_workers: int,
    execute_single: ExecuteSingle,
) -> list[ToolExecutionResult]:
    for item in tool_calls:
        emit_runtime_tool_event(
            item=item,
            stage="parallel_dispatch",
            batch_size=len(tool_calls),
        )
    if len(tool_calls) == 1:
        item = tool_calls[0]
        return [
            execute_single(
                item,
                context_budget,
                cache_store,
                cache_scope_keys.get(item.index),
                len(tool_calls),
            )
        ]

    unique_calls: list[ToolExecutionInput] = []
    duplicate_calls_by_representative: dict[int, list[ToolExecutionInput]] = {}
    representative_by_cache_key: dict[str, ToolExecutionInput] = {}
    for item in tool_calls:
        cache_scope_key = cache_scope_keys.get(item.index)
        item_cache_key = cache_key(item=item, cache_scope_key=cache_scope_key)
        if item_cache_key and item_cache_key in representative_by_cache_key:
            representative = representative_by_cache_key[item_cache_key]
            duplicate_calls_by_representative.setdefault(representative.index, []).append(item)
            continue
        unique_calls.append(item)
        if item_cache_key:
            representative_by_cache_key[item_cache_key] = item

    workers = max(1, min(len(unique_calls), max_parallel_workers))
    pool = _parallel_executor(workers)
    futures = []
    for item in unique_calls:
        ctx = copy_context()
        futures.append(
            pool.submit(
                ctx.run,
                execute_single,
                item,
                context_budget,
                cache_store,
                cache_scope_keys.get(item.index),
                len(tool_calls),
            )
        )
    results = [future.result() for future in futures]
    results_by_index = {result.index: result for result in results}
    for representative in unique_calls:
        source = results_by_index[representative.index]
        for duplicate in duplicate_calls_by_representative.get(representative.index, []):
            cache_scope_key = cache_scope_keys.get(duplicate.index)
            emit_runtime_tool_event(
                item=duplicate,
                stage="cache_hit",
                cache_scope=(cache_scope_key or "thread:default"),
                deduplicated=True,
            )
            results.append(
                copy_result_for_tool_call(
                    source=source,
                    item=duplicate,
                    cache_hit=source.message.status != "error",
                )
            )
    return results
