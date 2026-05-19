from __future__ import annotations

import atexit
import os
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

_DEFAULT_MAX_WORKERS = max(8, min(32, (os.cpu_count() or 1) + 4))


class _ObservedThreadPoolExecutor(ThreadPoolExecutor):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._active_lock = threading.Lock()
        self._active_workers = 0
        super().__init__(*args, **kwargs)

    def submit(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any):  # type: ignore[override]
        return super().submit(self._run_observed, fn, args, kwargs)

    def _run_observed(
        self,
        fn: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        with self._active_lock:
            self._active_workers += 1
        try:
            return fn(*args, **kwargs)
        finally:
            with self._active_lock:
                self._active_workers -= 1

    def active_workers(self) -> int:
        with self._active_lock:
            return self._active_workers

    def queued_tasks(self) -> int:
        queue = getattr(self, "_work_queue", None)
        qsize = getattr(queue, "qsize", None)
        if qsize is None:
            return 0
        try:
            return max(0, int(qsize()))
        except Exception:  # noqa: BLE001
            return 0


_shared_thread_pool_lock = threading.Lock()
_tool_thread_pool_lock = threading.Lock()
_shared_thread_pool: _ObservedThreadPoolExecutor | None = None
_tool_thread_pool: _ObservedThreadPoolExecutor | None = None


def shared_thread_pool() -> ThreadPoolExecutor:
    global _shared_thread_pool
    with _shared_thread_pool_lock:
        if _shared_thread_pool is None:
            _shared_thread_pool = _ObservedThreadPoolExecutor(
                max_workers=_DEFAULT_MAX_WORKERS,
                thread_name_prefix="focus-agent",
            )
        return _shared_thread_pool


def tool_thread_pool() -> ThreadPoolExecutor:
    global _tool_thread_pool
    with _tool_thread_pool_lock:
        if _tool_thread_pool is None:
            _tool_thread_pool = _ObservedThreadPoolExecutor(
                max_workers=_DEFAULT_MAX_WORKERS,
                thread_name_prefix="focus-agent-tool",
            )
        return _tool_thread_pool


def shutdown_shared_thread_pool() -> None:
    global _shared_thread_pool
    with _shared_thread_pool_lock:
        pool = _shared_thread_pool
        _shared_thread_pool = None
    if pool is not None:
        pool.shutdown(wait=False, cancel_futures=True)


def shutdown_tool_thread_pool() -> None:
    global _tool_thread_pool
    with _tool_thread_pool_lock:
        pool = _tool_thread_pool
        _tool_thread_pool = None
    if pool is not None:
        pool.shutdown(wait=False, cancel_futures=True)


def shutdown_thread_pool() -> None:
    shutdown_shared_thread_pool()
    shutdown_tool_thread_pool()


def thread_pool_max_workers() -> int:
    return _DEFAULT_MAX_WORKERS


def tool_pool_active_workers() -> int:
    pool = _tool_thread_pool
    return pool.active_workers() if pool is not None else 0


def tool_pool_queue_size() -> int:
    pool = _tool_thread_pool
    return pool.queued_tasks() if pool is not None else 0


atexit.register(shutdown_thread_pool)
