from __future__ import annotations

import time
from typing import Any

from ..core.context_policy import trim_tool_observation
from ..core.types import ContextBudget
from ..observability.tracing import start_trace_span
from .tool_cache import ToolResultCacheStore, cache_key
from .tool_events import emit_runtime_tool_event
from .tool_execution_types import ToolExecutionInput, ToolExecutionResult
from .tool_invocation import (
    ToolParameterValidationError,
    error_event_payload,
    error_stage_for_exception,
    invoke_tool,
    runtime_info_for_error,
    should_bypass_fallback,
)
from .tool_messages import (
    annotate_tool_result_runtime,
    build_tool_error_message,
    build_tool_message,
)


def execute_single(
    item: ToolExecutionInput,
    context_budget: ContextBudget,
    cache_store: ToolResultCacheStore | None,
    cache_scope_key: str | None,
    parallel_batch_size: int | None,
) -> ToolExecutionResult:
    started_at = time.perf_counter()
    if item.runtime.side_effect:
        emit_runtime_tool_event(
            item=item,
            stage="serialized_side_effect",
            side_effect_kind=item.runtime.side_effect_kind,
        )
    with start_trace_span(
        name="focus_agent.tool",
        attributes={
            "focus_agent.tool.name": item.tool_name,
            "focus_agent.tool.index": item.index,
            "focus_agent.tool.cache_scope": cache_scope_key or "thread:default",
            "focus_agent.tool.parallel_batch_size": parallel_batch_size or 1,
        },
    ) as span:
        result = execute_single_untraced(
            item,
            context_budget=context_budget,
            cache_store=cache_store,
            cache_scope_key=cache_scope_key,
            parallel_batch_size=parallel_batch_size,
        )
        duration_ms = (time.perf_counter() - started_at) * 1000
        annotate_tool_result_runtime(
            result,
            {
                **span.runtime_payload(),
                "duration_ms": round(duration_ms, 3),
            },
        )
        return result


def execute_single_untraced(
    item: ToolExecutionInput,
    context_budget: ContextBudget,
    cache_store: ToolResultCacheStore | None,
    cache_scope_key: str | None,
    parallel_batch_size: int | None,
) -> ToolExecutionResult:
    try:
        if item.runtime.validator is not None:
            try:
                item.runtime.validator(item.args)
            except Exception as validation_exc:  # noqa: BLE001
                raise ToolParameterValidationError(
                    tool_name=item.tool_name,
                    error=validation_exc,
                ) from validation_exc
        item_cache_key = cache_key(item=item, cache_scope_key=cache_scope_key)
        if item_cache_key and cache_store is not None and cache_store.get(item_cache_key) is not None:
            observation = cache_store.get(item_cache_key) or ""
            trimmed_observation, trim_runtime, prompt_observation = trim_success(
                observation,
                tool_name=item.tool_name,
                tool_call_id=item.tool_call_id,
                context_budget=context_budget,
                max_chars=item.runtime.max_observation_chars,
            )
            emit_runtime_tool_event(
                item=item,
                stage="cache_hit",
                cache_scope=(cache_scope_key or "thread:default"),
            )
            return ToolExecutionResult(
                index=item.index,
                cache_hit=True,
                message=build_tool_message(
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
        emit_runtime_tool_event(
            item=item,
            stage=error_stage_for_exception(exc),
            error=str(exc),
            **error_event_payload(exc),
        )
        return ToolExecutionResult(
            index=item.index,
            message=build_tool_error_message(
                tool_call_id=item.tool_call_id,
                tool_name=item.tool_name,
                args=item.args,
                error=exc,
                runtime_info=runtime_info_for_error(exc=exc, parallel_batch_size=parallel_batch_size),
            ),
        )

    try:
        emit_runtime_tool_event(item=item, stage="invoke")
        observation = invoke_tool(item)
        text = str(observation)
        if item_cache_key and cache_store is not None:
            cache_store.set(item_cache_key, text)
        trimmed_text, trim_runtime, prompt_observation = trim_success(
            text,
            tool_name=item.tool_name,
            tool_call_id=item.tool_call_id,
            context_budget=context_budget,
            max_chars=item.runtime.max_observation_chars,
        )
        return ToolExecutionResult(
            index=item.index,
            message=build_tool_message(
                content=trimmed_text,
                tool_call_id=item.tool_call_id,
                tool_name=item.tool_name,
                prompt_observation=prompt_observation,
                runtime_info={
                    "cache_hit": False,
                    "fallback_used": False,
                    "parallel_batch_size": parallel_batch_size if (parallel_batch_size or 0) > 1 else None,
                    **side_effect_runtime_info(item),
                    **trim_runtime,
                },
            ),
        )
    except Exception as exc:  # noqa: BLE001
        if item.runtime.fallback_handler is not None and not should_bypass_fallback(exc):
            try:
                emit_runtime_tool_event(
                    item=item,
                    stage="fallback_attempt",
                    fallback_group=item.runtime.fallback_group,
                    error=str(exc),
                )
                fallback_observation = item.runtime.fallback_handler(exc, item.args)
                fallback_text = str(fallback_observation)
                trimmed_fallback, trim_runtime, prompt_observation = trim_success(
                    fallback_text,
                    tool_name=item.tool_name,
                    tool_call_id=item.tool_call_id,
                    context_budget=context_budget,
                    max_chars=item.runtime.max_observation_chars,
                )
                emit_runtime_tool_event(
                    item=item,
                    stage="fallback_success",
                    fallback_group=item.runtime.fallback_group,
                )
                return ToolExecutionResult(
                    index=item.index,
                    message=build_tool_message(
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
                emit_runtime_tool_event(
                    item=item,
                    stage="fallback_error",
                    fallback_group=item.runtime.fallback_group,
                    error=str(fallback_exc),
                )
                exc = fallback_exc
        emit_runtime_tool_event(
            item=item,
            stage=error_stage_for_exception(exc),
            error=str(exc),
            **error_event_payload(exc),
        )
        return ToolExecutionResult(
            index=item.index,
            message=build_tool_error_message(
                tool_call_id=item.tool_call_id,
                tool_name=item.tool_name,
                args=item.args,
                error=exc,
                runtime_info=runtime_info_for_error(exc=exc, parallel_batch_size=parallel_batch_size),
            ),
        )


def trim_success(
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


def side_effect_runtime_info(item: ToolExecutionInput) -> dict[str, Any]:
    if not item.runtime.side_effect:
        return {}
    runtime_info: dict[str, Any] = {"side_effect_serialized": True}
    if item.runtime.side_effect_kind:
        runtime_info["side_effect_kind"] = item.runtime.side_effect_kind
    return runtime_info
