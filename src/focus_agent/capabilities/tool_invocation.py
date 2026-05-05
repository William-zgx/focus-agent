from __future__ import annotations

from concurrent.futures import CancelledError as FutureCancelledError
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from contextvars import copy_context
import atexit
import threading
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


_TOOL_INVOCATION_EXECUTOR_MAX_WORKERS = 8
_tool_invocation_executor_lock = threading.Lock()
_tool_invocation_executor_instance: ThreadPoolExecutor | None = None
_tool_invocation_timeout_active = 0
_tool_invocation_timeout_total = 0


def _tool_invocation_executor() -> ThreadPoolExecutor:
    global _tool_invocation_executor_instance
    with _tool_invocation_executor_lock:
        if _tool_invocation_executor_instance is None:
            _tool_invocation_executor_instance = ThreadPoolExecutor(
                max_workers=_TOOL_INVOCATION_EXECUTOR_MAX_WORKERS,
                thread_name_prefix="focus-agent-tool-timeout",
            )
        return _tool_invocation_executor_instance


def _shutdown_tool_invocation_executor() -> None:
    executor = _tool_invocation_executor_instance
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=True)


atexit.register(_shutdown_tool_invocation_executor)


def _mark_timed_out_future_active() -> None:
    global _tool_invocation_timeout_active, _tool_invocation_timeout_total
    with _tool_invocation_executor_lock:
        _tool_invocation_timeout_active += 1
        _tool_invocation_timeout_total += 1


def _mark_timed_out_future_done(_future: Any) -> None:
    global _tool_invocation_timeout_active
    with _tool_invocation_executor_lock:
        if _tool_invocation_timeout_active > 0:
            _tool_invocation_timeout_active -= 1


def _mark_timed_out_future_cancelled() -> None:
    global _tool_invocation_timeout_total
    with _tool_invocation_executor_lock:
        _tool_invocation_timeout_total += 1


def tool_invocation_runtime_snapshot() -> dict[str, int]:
    with _tool_invocation_executor_lock:
        return {
            "timeout_active": _tool_invocation_timeout_active,
            "timeout_total": _tool_invocation_timeout_total,
            "max_workers": _TOOL_INVOCATION_EXECUTOR_MAX_WORKERS,
        }


def invoke_tool(item: ToolExecutionInput) -> Any:
    timeout_seconds = effective_timeout_seconds(item.runtime)
    if timeout_seconds is None:
        return item.tool.invoke(item.args)
    return invoke_tool_with_timeout(item=item, timeout_seconds=timeout_seconds)


def invoke_tool_with_timeout(*, item: ToolExecutionInput, timeout_seconds: float) -> Any:
    ctx = copy_context()

    def _runner() -> Any:
        try:
            return ctx.run(item.tool.invoke, item.args)
        except BaseException as exc:  # noqa: BLE001
            if isinstance(exc, Exception):
                raise
            raise RuntimeError(
                f"Tool '{item.tool_name}' aborted with {type(exc).__name__}: {exc}"
            ) from exc

    future = _tool_invocation_executor().submit(_runner)
    try:
        return future.result(timeout=timeout_seconds)
    except FutureTimeoutError as exc:
        if not future.cancel():
            _mark_timed_out_future_active()
            future.add_done_callback(_mark_timed_out_future_done)
        else:
            _mark_timed_out_future_cancelled()
        raise ToolInvocationTimeoutError(
            tool_name=item.tool_name,
            timeout_seconds=timeout_seconds,
        ) from exc


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
