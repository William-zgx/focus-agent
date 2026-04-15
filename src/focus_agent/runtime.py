"""Compatibility shim.

Canonical import:
    from focus_agent.engine.runtime import AppRuntime, create_runtime
"""

from .engine.runtime import AppRuntime, create_runtime

__all__ = [
    "AppRuntime",
    "create_runtime",
]
