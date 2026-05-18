from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import TimeoutError as FuturesTimeoutError
from contextvars import copy_context
from typing import Any

from focus_agent.runtime.thread_pool import shared_thread_pool


class ToolExecutionTimeout(TimeoutError):  # noqa: N818 - public compatibility name
    def __init__(self, message: str, *, active: bool = False) -> None:
        self.active = active
        super().__init__(message)


class ToolExecutionDenied(RuntimeError):  # noqa: N818 - public compatibility name
    pass


class ToolAuditLog:
    def record_start(self, tool_name: str) -> None:
        return None

    def record_success(self, tool_name: str) -> None:
        return None

    def record_timeout(self, tool_name: str) -> None:
        return None

    def record_failure(self, tool_name: str, error: str) -> None:
        return None


_semaphores: dict[str, threading.Semaphore] = {}
_semaphores_lock = threading.Lock()


def run_in_sandbox_sync(
    fn: Callable[[], Any],
    *,
    tool_name: str,
    timeout_seconds: float | None,
    max_concurrent_calls: int = 4,
    audit_log: ToolAuditLog | None = None,
) -> Any:
    audit = audit_log or ToolAuditLog()
    semaphore = _semaphore_for(tool_name, max_concurrent_calls)
    if not semaphore.acquire(blocking=False):
        raise ToolExecutionDenied(f"Tool {tool_name} exceeded concurrency limit.")
    audit.record_start(tool_name)
    ctx = copy_context()
    future = shared_thread_pool().submit(ctx.run, fn)
    try:
        result = future.result(timeout=timeout_seconds)
    except FuturesTimeoutError as exc:
        audit.record_timeout(tool_name)
        if not future.cancel():
            future.add_done_callback(lambda _future: semaphore.release())
            raise ToolExecutionTimeout(
                f"Tool {tool_name} exceeded {timeout_seconds:g}s.",
                active=True,
            ) from exc
        raise ToolExecutionTimeout(
            f"Tool {tool_name} exceeded {timeout_seconds:g}s.",
            active=False,
        ) from exc
    except Exception as exc:
        audit.record_failure(tool_name, repr(exc))
        raise
    else:
        audit.record_success(tool_name)
        return result
    finally:
        if future.done() or future.cancelled():
            semaphore.release()


def _semaphore_for(tool_name: str, max_concurrent_calls: int) -> threading.Semaphore:
    key = f"{tool_name}:{max(1, int(max_concurrent_calls or 1))}"
    with _semaphores_lock:
        semaphore = _semaphores.get(key)
        if semaphore is None:
            semaphore = threading.Semaphore(max(1, int(max_concurrent_calls or 1)))
            _semaphores[key] = semaphore
        return semaphore


__all__ = [
    "ToolAuditLog",
    "ToolExecutionDenied",
    "ToolExecutionTimeout",
    "run_in_sandbox_sync",
]
