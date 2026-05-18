from __future__ import annotations

import atexit
import os
import threading
from concurrent.futures import ThreadPoolExecutor

_DEFAULT_MAX_WORKERS = max(8, min(32, (os.cpu_count() or 1) + 4))
_thread_pool_lock = threading.Lock()
_thread_pool: ThreadPoolExecutor | None = None


def shared_thread_pool() -> ThreadPoolExecutor:
    global _thread_pool
    with _thread_pool_lock:
        if _thread_pool is None:
            _thread_pool = ThreadPoolExecutor(
                max_workers=_DEFAULT_MAX_WORKERS,
                thread_name_prefix="focus-agent",
            )
        return _thread_pool


def shutdown_thread_pool() -> None:
    global _thread_pool
    with _thread_pool_lock:
        pool = _thread_pool
        _thread_pool = None
    if pool is not None:
        pool.shutdown(wait=False, cancel_futures=True)


def thread_pool_max_workers() -> int:
    return _DEFAULT_MAX_WORKERS


atexit.register(shutdown_thread_pool)
