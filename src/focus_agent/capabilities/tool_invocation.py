from __future__ import annotations

from concurrent.futures import CancelledError as FutureCancelledError
from contextvars import copy_context
from threading import Thread
from typing import Any

from .tool_execution_types import ToolExecutionInput
from .tool_registry import ToolRuntimeMeta


class ToolInvocationTimeoutError(TimeoutError):
    def __init__(self, *, tool_name: str, timeout_seconds: float) -> None:
        self.tool_name = tool_name
        self.timeout_seconds = timeout_seconds
        super().__init__(f"Tool '{tool_name}' timed out after {timeout_seconds:g}s.")


class ToolParameterValidationError(ValueError):
    def __init__(self, *, tool_name: str, error: Exception | str) -> None:
        self.tool_name = tool_name
        self.validation_error = str(error)
        super().__init__(f"Tool '{tool_name}' parameter validation failed: {error}")


def invoke_tool(item: ToolExecutionInput) -> Any:
    timeout_seconds = effective_timeout_seconds(item.runtime)
    if timeout_seconds is None:
        return item.tool.invoke(item.args)
    return invoke_tool_with_timeout(item=item, timeout_seconds=timeout_seconds)


def invoke_tool_with_timeout(*, item: ToolExecutionInput, timeout_seconds: float) -> Any:
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


def effective_timeout_seconds(runtime: ToolRuntimeMeta) -> float | None:
    if runtime.side_effect:
        return None
    if runtime.timeout_seconds is None or runtime.timeout_seconds <= 0:
        return None
    return runtime.timeout_seconds


def should_bypass_fallback(error: Exception) -> bool:
    return isinstance(error, (ToolInvocationTimeoutError, FutureCancelledError, ToolParameterValidationError))


def error_stage_for_exception(error: Exception) -> str:
    if isinstance(error, ToolParameterValidationError):
        return "validation_error"
    if isinstance(error, ToolInvocationTimeoutError):
        return "timeout"
    if isinstance(error, FutureCancelledError):
        return "cancelled"
    return "error"


def error_event_payload(error: Exception) -> dict[str, Any]:
    if isinstance(error, ToolParameterValidationError):
        return {"validation_error": error.validation_error}
    if isinstance(error, ToolInvocationTimeoutError):
        return {"timeout_seconds": error.timeout_seconds}
    return {}


def runtime_info_for_error(
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
    if isinstance(exc, ToolParameterValidationError):
        runtime_info["validation_failed"] = True
        runtime_info["validation_error"] = exc.validation_error
    return runtime_info
