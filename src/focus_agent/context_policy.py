"""Compatibility shim.

Canonical import:
    from focus_agent.core.context_policy import ContextSlice, assemble_context
"""

from .core.context_policy import ContextSlice, assemble_context

__all__ = [
    "ContextSlice",
    "assemble_context",
]
