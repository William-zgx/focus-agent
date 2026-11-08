"""Runtime compatibility exports and shared runtime utilities."""

from .thread_pool import (
    shared_thread_pool,
    shutdown_thread_pool,
    thread_pool_max_workers,
    tool_thread_pool,
)


def __getattr__(name: str):
    if name in {"AppRuntime", "create_runtime", "ensure_runtime_directories"}:
        from focus_agent.engine import runtime as engine_runtime

        return getattr(engine_runtime, name)
    raise AttributeError(name)


__all__ = [
    "AppRuntime",
    "create_runtime",
    "ensure_runtime_directories",
    "shared_thread_pool",
    "shutdown_thread_pool",
    "thread_pool_max_workers",
    "tool_thread_pool",
]
