from __future__ import annotations

from concurrent.futures import CancelledError as FutureCancelledError
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass, field
import hashlib
import json
from threading import Thread
import time
from typing import Any

from langchain.messages import ToolMessage
from langgraph.config import get_stream_writer

from ..core.context_policy import trim_tool_observation
from ..core.types import ContextBudget
from ..observability.tracing import current_trace_runtime_payload, start_trace_span
from .tool_registry import ToolRuntimeMeta


@dataclass(slots=True)
class ToolExecutionInput:
    index: int
    tool_call_id: str
    tool_name: str
    args: dict[str, Any]
    tool: Any
    runtime: ToolRuntimeMeta


@dataclass(slots=True)
class ToolExecutionResult:
    index: int
    message: ToolMessage
    cache_hit: bool = False


@dataclass(slots=True)
class ToolResultCacheStore:
    turn: dict[str, str] = field(default_factory=dict)
    thread: dict[str, str] = field(default_factory=dict)
    branch: dict[str, str] = field(default_factory=dict)

    def get(self, key: str) -> str | None:
        return self._cache_for_key(key).get(key)

    def set(self, key: str, value: str) -> None:
        self._cache_for_key(key)[key] = value

    def invalidate_namespace(self, namespace: str | None) -> None:
        if not namespace:
            return
        cache = self._cache_for_namespace(namespace)
        prefix = f"{namespace}:"
        for key in list(cache):
            if key.startswith(prefix):
                del cache[key]

    def _cache_for_key(self, key: str) -> dict[str, str]:
        return self._cache_for_scope(key.split(":", 1)[0])

    def _cache_for_namespace(self, namespace: str) -> dict[str, str]:
        return self._cache_for_scope(namespace.split(":", 1)[0])

    def _cache_for_scope(self, scope: str) -> dict[str, str]:
        normalized = scope.strip().lower()
        if normalized == "turn":
            return self.turn
        if normalized == "branch":
            return self.branch
        return self.thread


class ToolInvocationTimeoutError(TimeoutError):
    def __init__(self, *, tool_name: str, timeout_seconds: float) -> None:
        self.tool_name = tool_name
        self.timeout_seconds = timeout_seconds
        super().__init__(f"Tool '{tool_name}' timed out after {timeout_seconds:g}s.")


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
        if item.runtime.parallel_safe and not item.runtime.side_effect:
            pending_parallel.append(item)
            continue
        if pending_parallel:
            completed.extend(
                _run_parallel_batch(
                    pending_parallel,
                    context_budget=context_budget,
                    cache_store=cache_store,
                    cache_scope_keys=cache_scope_keys or {},
                    max_parallel_workers=max_parallel_workers,
                )
            )
            pending_parallel = []
        completed.append(
            _execute_single(
                item,
                context_budget=context_budget,
                cache_store=cache_store,
                cache_scope_key=(cache_scope_keys or {}).get(item.index),
                parallel_batch_size=None,
            )
        )
        if item.runtime.side_effect and completed[-1].message.status != "error":
            _invalidate_after_side_effect(
                cache_store=cache_store,
                invalidation_scope_keys=invalidation_scope_keys or [],
            )

    if pending_parallel:
        completed.extend(
            _run_parallel_batch(
                pending_parallel,
                context_budget=context_budget,
                cache_store=cache_store,
                cache_scope_keys=cache_scope_keys or {},
                max_parallel_workers=max_parallel_workers,
            )
        )

    completed.sort(key=lambda item: item.index)
    return completed


def build_tool_error_message(
    *,
    tool_call_id: str,
    tool_name: str,
    args: dict[str, Any],
    error: Exception | str,
    runtime_info: dict[str, Any] | None = None,
) -> ToolMessage:
    payload = {
        "status": "error",
        "tool": tool_name,
        "args": args,
        "error": str(error),
    }
    merged_runtime_info = {"cache_hit": False, "fallback_used": False, **dict(runtime_info or {})}
    return _build_tool_message(
        content=json.dumps(payload, ensure_ascii=False),
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        status="error",
        runtime_info=merged_runtime_info,
    )


def build_cache_scope_key(
    *,
    scope: str,
    root_thread_id: str | None = None,
    branch_id: str | None = None,
    turn_id: str | None = None,
) -> str:
    normalized_scope = (scope or "thread").strip().lower()
    if normalized_scope == "branch" and branch_id:
        return f"branch:{branch_id}"
    if normalized_scope == "turn":
        return f"turn:{root_thread_id or branch_id or 'default'}:{turn_id or 'default'}"
    return f"thread:{root_thread_id or branch_id or 'default'}"


def _run_parallel_batch(
    tool_calls: list[ToolExecutionInput],
    *,
    context_budget: ContextBudget,
    cache_store: ToolResultCacheStore | None,
    cache_scope_keys: dict[int, str],
    max_parallel_workers: int,
) -> list[ToolExecutionResult]:
    for item in tool_calls:
        _emit_runtime_tool_event(
            item=item,
            stage="parallel_dispatch",
            batch_size=len(tool_calls),
        )
    if len(tool_calls) == 1:
        item = tool_calls[0]
        return [
            _execute_single(
                item,
                context_budget=context_budget,
                cache_store=cache_store,
                cache_scope_key=cache_scope_keys.get(item.index),
                parallel_batch_size=len(tool_calls),
            )
        ]

    unique_calls: list[ToolExecutionInput] = []
    duplicate_calls_by_representative: dict[int, list[ToolExecutionInput]] = {}
    representative_by_cache_key: dict[str, ToolExecutionInput] = {}
    for item in tool_calls:
        cache_scope_key = cache_scope_keys.get(item.index)
        cache_key = _cache_key(item=item, cache_scope_key=cache_scope_key)
        if cache_key and cache_key in representative_by_cache_key:
            representative = representative_by_cache_key[cache_key]
            duplicate_calls_by_representative.setdefault(representative.index, []).append(item)
            continue
        unique_calls.append(item)
        if cache_key:
            representative_by_cache_key[cache_key] = item

    workers = max(1, min(len(unique_calls), max_parallel_workers))
    futures = []
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="focus-agent-tool") as pool:
        for item in unique_calls:
            ctx = copy_context()
            futures.append(
                pool.submit(
                    ctx.run,
                    _execute_single,
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
            _emit_runtime_tool_event(
                item=duplicate,
                stage="cache_hit",
                cache_scope=(cache_scope_key or "thread:default"),
                deduplicated=True,
            )
            results.append(
                _copy_result_for_tool_call(
                    source=source,
                    item=duplicate,
                    cache_hit=source.message.status != "error",
                )
            )
    return results


def _execute_single(
    item: ToolExecutionInput,
    context_budget: ContextBudget,
    cache_store: ToolResultCacheStore | None,
    cache_scope_key: str | None,
    parallel_batch_size: int | None,
) -> ToolExecutionResult:
    started_at = time.perf_counter()
    with start_trace_span(
        name="focus_agent.tool",
        attributes={
            "focus_agent.tool.name": item.tool_name,
            "focus_agent.tool.index": item.index,
            "focus_agent.tool.cache_scope": cache_scope_key or "thread:default",
            "focus_agent.tool.parallel_batch_size": parallel_batch_size or 1,
        },
    ) as span:
        result = _execute_single_untraced(
            item,
            context_budget=context_budget,
            cache_store=cache_store,
            cache_scope_key=cache_scope_key,
            parallel_batch_size=parallel_batch_size,
        )
        duration_ms = (time.perf_counter() - started_at) * 1000
        _annotate_tool_result_runtime(
            result,
            {
                **span.runtime_payload(),
                "duration_ms": round(duration_ms, 3),
            },
        )
        return result


def _execute_single_untraced(
    item: ToolExecutionInput,
    context_budget: ContextBudget,
    cache_store: ToolResultCacheStore | None,
    cache_scope_key: str | None,
    parallel_batch_size: int | None,
) -> ToolExecutionResult:
    try:
        if item.runtime.validator is not None:
            item.runtime.validator(item.args)
        cache_key = _cache_key(item=item, cache_scope_key=cache_scope_key)
        if cache_key and cache_store is not None and cache_store.get(cache_key) is not None:
            observation = cache_store.get(cache_key) or ""
            trimmed_observation, trim_runtime, prompt_observation = _trim_success(
                observation,
                tool_name=item.tool_name,
                tool_call_id=item.tool_call_id,
                context_budget=context_budget,
                max_chars=item.runtime.max_observation_chars,
            )
            _emit_runtime_tool_event(
                item=item,
                stage="cache_hit",
                cache_scope=(cache_scope_key or "thread:default"),
            )
            return ToolExecutionResult(
                index=item.index,
                cache_hit=True,
                message=_build_tool_message(
                    content=trimmed_observation,
                    tool_call_id=item.tool_call_id,
                    tool_name=item.tool_name,
                    prompt_observation=prompt_observation,
                    runtime_info={
                        "cache_hit": True,
                        "fallback_used": False,
                        "parallel_batch_size": parallel_batch_size if (parallel_batch_size or 0) > 1 else None,
                        **trim_runtime,
                    },
                ),
            )
    except Exception as exc:  # noqa: BLE001
        _emit_runtime_tool_event(item=item, stage="error", error=str(exc))
        return ToolExecutionResult(
            index=item.index,
            message=build_tool_error_message(
                tool_call_id=item.tool_call_id,
                tool_name=item.tool_name,
                args=item.args,
                error=exc,
            ),
        )

    try:
        _emit_runtime_tool_event(item=item, stage="invoke")
        observation = _invoke_tool(item)
        text = str(observation)
        if cache_key and cache_store is not None:
            cache_store.set(cache_key, text)
        trimmed_text, trim_runtime, prompt_observation = _trim_success(
            text,
            tool_name=item.tool_name,
            tool_call_id=item.tool_call_id,
            context_budget=context_budget,
            max_chars=item.runtime.max_observation_chars,
        )
        return ToolExecutionResult(
            index=item.index,
            message=_build_tool_message(
                content=trimmed_text,
                tool_call_id=item.tool_call_id,
                tool_name=item.tool_name,
                prompt_observation=prompt_observation,
                runtime_info={
                    "cache_hit": False,
                    "fallback_used": False,
                    "parallel_batch_size": parallel_batch_size if (parallel_batch_size or 0) > 1 else None,
                    **trim_runtime,
                },
            ),
        )
    except Exception as exc:  # noqa: BLE001
        if item.runtime.fallback_handler is not None and not _should_bypass_fallback(exc):
            try:
                _emit_runtime_tool_event(
                    item=item,
                    stage="fallback_attempt",
                    fallback_group=item.runtime.fallback_group,
                    error=str(exc),
                )
                fallback_observation = item.runtime.fallback_handler(exc, item.args)
                fallback_text = str(fallback_observation)
                trimmed_fallback, trim_runtime, prompt_observation = _trim_success(
                    fallback_text,
                    tool_name=item.tool_name,
                    tool_call_id=item.tool_call_id,
                    context_budget=context_budget,
                    max_chars=item.runtime.max_observation_chars,
                )
                _emit_runtime_tool_event(
                    item=item,
                    stage="fallback_success",
                    fallback_group=item.runtime.fallback_group,
                )
                return ToolExecutionResult(
                    index=item.index,
                    message=_build_tool_message(
                        content=trimmed_fallback,
                        tool_call_id=item.tool_call_id,
                        tool_name=item.tool_name,
                        prompt_observation=prompt_observation,
                        runtime_info={
                            "cache_hit": False,
                            "fallback_used": True,
                            "fallback_group": item.runtime.fallback_group,
                            "parallel_batch_size": parallel_batch_size if (parallel_batch_size or 0) > 1 else None,
                            **trim_runtime,
                        },
                    ),
                )
            except Exception as fallback_exc:  # noqa: BLE001
                _emit_runtime_tool_event(
                    item=item,
                    stage="fallback_error",
                    fallback_group=item.runtime.fallback_group,
                    error=str(fallback_exc),
                )
                exc = fallback_exc
        _emit_runtime_tool_event(
            item=item,
            stage=_error_stage_for_exception(exc),
            error=str(exc),
            **_error_event_payload(exc),
        )
        return ToolExecutionResult(
            index=item.index,
            message=build_tool_error_message(
                tool_call_id=item.tool_call_id,
                tool_name=item.tool_name,
                args=item.args,
                error=exc,
                runtime_info=_runtime_info_for_error(exc=exc, parallel_batch_size=parallel_batch_size),
            ),
        )


def _trim_success(
    observation: str,
    *,
    tool_name: str,
    tool_call_id: str,
    context_budget: ContextBudget,
    max_chars: int | None,
) -> tuple[str, dict[str, Any], str | None]:
    trimmed = trim_tool_observation(
        observation,
        tool_name=tool_name,
        budget=context_budget,
        max_chars=max_chars,
    )
    runtime_info: dict[str, Any] = {}
    prompt_observation: str | None = None
    if trimmed != observation:
        runtime_info.update(
            {
                "observation_prompt_compacted": True,
                "observation_original_chars": len(observation),
                "observation_trimmed_chars": len(trimmed),
            }
        )
        prompt_observation = trim_tool_observation(
            observation,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            budget=context_budget,
            max_chars=max(
                160,
                int(context_budget.tool_reference_token_limit) * max(1, int(context_budget.chars_per_token)),
            ),
            artifactize_for_prompt=True,
            force_artifactize=True,
        )
    return trimmed, runtime_info, prompt_observation


def _invoke_tool(item: ToolExecutionInput) -> Any:
    timeout_seconds = _effective_timeout_seconds(item.runtime)
    if timeout_seconds is None:
        return item.tool.invoke(item.args)
    return _invoke_tool_with_timeout(item=item, timeout_seconds=timeout_seconds)


def _invoke_tool_with_timeout(*, item: ToolExecutionInput, timeout_seconds: float) -> Any:
    outcome: dict[str, Any] = {}
    error: dict[str, Exception] = {}
    ctx = copy_context()

    def _runner() -> None:
        try:
            outcome["value"] = ctx.run(item.tool.invoke, item.args)
        except BaseException as exc:  # noqa: BLE001
            if isinstance(exc, Exception):
                error["value"] = exc
            else:
                error["value"] = RuntimeError(
                    f"Tool '{item.tool_name}' aborted with {type(exc).__name__}: {exc}"
                )

    worker = Thread(
        target=_runner,
        name=f"focus-agent-tool-timeout-{item.tool_name}",
        daemon=True,
    )
    worker.start()
    worker.join(timeout_seconds)
    if worker.is_alive():
        raise ToolInvocationTimeoutError(
            tool_name=item.tool_name,
            timeout_seconds=timeout_seconds,
        )
    if "value" in error:
        raise error["value"]
    return outcome.get("value")


def _effective_timeout_seconds(runtime: ToolRuntimeMeta) -> float | None:
    if runtime.side_effect:
        return None
    if runtime.timeout_seconds is None or runtime.timeout_seconds <= 0:
        return None
    return runtime.timeout_seconds


def _should_bypass_fallback(error: Exception) -> bool:
    return isinstance(error, (ToolInvocationTimeoutError, FutureCancelledError))


def _error_stage_for_exception(error: Exception) -> str:
    if isinstance(error, ToolInvocationTimeoutError):
        return "timeout"
    if isinstance(error, FutureCancelledError):
        return "cancelled"
    return "error"


def _error_event_payload(error: Exception) -> dict[str, Any]:
    if isinstance(error, ToolInvocationTimeoutError):
        return {"timeout_seconds": error.timeout_seconds}
    return {}


def _runtime_info_for_error(
    *,
    exc: Exception,
    parallel_batch_size: int | None,
) -> dict[str, Any]:
    runtime_info: dict[str, Any] = {
        "cache_hit": False,
        "fallback_used": False,
        "parallel_batch_size": parallel_batch_size if (parallel_batch_size or 0) > 1 else None,
    }
    if isinstance(exc, ToolInvocationTimeoutError):
        runtime_info["timed_out"] = True
        runtime_info["timeout_seconds"] = exc.timeout_seconds
    if isinstance(exc, FutureCancelledError):
        runtime_info["cancelled"] = True
    return runtime_info


def _build_tool_message(
    *,
    content: str,
    tool_call_id: str,
    tool_name: str,
    prompt_observation: str | None = None,
    status: str = "success",
    runtime_info: dict[str, Any] | None = None,
) -> ToolMessage:
    artifact = {
        "runtime": dict(runtime_info or {}),
        "tool_name": tool_name,
    }
    if prompt_observation:
        artifact["prompt_observation"] = prompt_observation
    return ToolMessage(
        content=content,
        tool_call_id=tool_call_id,
        status=status,  # type: ignore[arg-type]
        artifact=artifact,
    )


def _copy_result_for_tool_call(
    *,
    source: ToolExecutionResult,
    item: ToolExecutionInput,
    cache_hit: bool,
) -> ToolExecutionResult:
    artifact = getattr(source.message, "artifact", None)
    runtime_info = {}
    prompt_observation = None
    if isinstance(artifact, dict) and isinstance(artifact.get("runtime"), dict):
        runtime_info = dict(artifact.get("runtime") or {})
        if isinstance(artifact.get("prompt_observation"), str):
            prompt_observation = str(artifact.get("prompt_observation"))
    runtime_info["deduplicated"] = True
    if cache_hit:
        runtime_info["cache_hit"] = True
    return ToolExecutionResult(
        index=item.index,
        cache_hit=cache_hit,
        message=_build_tool_message(
            content=str(source.message.content),
            tool_call_id=item.tool_call_id,
            tool_name=item.tool_name,
            prompt_observation=prompt_observation,
            status=getattr(source.message, "status", "success"),
            runtime_info=runtime_info,
        ),
    )


def _annotate_tool_result_runtime(result: ToolExecutionResult, runtime_info: dict[str, Any]) -> None:
    clean_runtime_info = {key: value for key, value in runtime_info.items() if value is not None}
    if not clean_runtime_info:
        return
    artifact = getattr(result.message, "artifact", None)
    if not isinstance(artifact, dict):
        artifact = {}
    existing_runtime = artifact.get("runtime")
    merged_runtime = dict(existing_runtime or {}) if isinstance(existing_runtime, dict) else {}
    for key, value in clean_runtime_info.items():
        merged_runtime.setdefault(key, value)
    artifact["runtime"] = merged_runtime
    result.message.artifact = artifact


def _cache_key(item: ToolExecutionInput, cache_scope_key: str | None) -> str | None:
    if not item.runtime.cacheable:
        return None
    scope_key = cache_scope_key or "thread:default"
    args_json = json.dumps(item.args, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(f"{scope_key}|{item.tool_name}|{args_json}".encode("utf-8")).hexdigest()
    return f"{scope_key}:{digest}"


def _invalidate_after_side_effect(
    *,
    cache_store: ToolResultCacheStore | None,
    invalidation_scope_keys: list[str],
) -> None:
    if cache_store is None:
        return
    for scope_key in invalidation_scope_keys:
        cache_store.invalidate_namespace(scope_key)


def _emit_runtime_tool_event(
    *,
    item: ToolExecutionInput,
    stage: str,
    **payload: Any,
) -> None:
    try:
        writer = get_stream_writer()
    except Exception:  # noqa: BLE001
        return
    metadata = getattr(item.tool, "metadata", None)
    display_name = metadata.get("display_name") if isinstance(metadata, dict) else None
    writer(
        {
            "event": "tool",
            "tool_name": item.tool_name,
            "display_name": display_name,
            "stage": stage,
            **current_trace_runtime_payload(),
            **payload,
        }
    )
