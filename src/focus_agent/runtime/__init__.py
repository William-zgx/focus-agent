"""Runtime compatibility exports and shared runtime utilities."""

from .model_router import ModelChoice, ModelRouter, ModelRouterDecision, TaskKind
from .thread_pool import shared_thread_pool, shutdown_thread_pool, thread_pool_max_workers


def __getattr__(name: str):
    if name in {"AppRuntime", "create_runtime", "ensure_runtime_directories"}:
        from focus_agent.engine import runtime as engine_runtime

        return getattr(engine_runtime, name)
    raise AttributeError(name)


__all__ = [
    "AppRuntime",
    "create_runtime",
    "ensure_runtime_directories",
    "ModelChoice",
    "ModelRouter",
    "ModelRouterDecision",
    "shared_thread_pool",
    "shutdown_thread_pool",
    "TaskKind",
    "thread_pool_max_workers",
]
