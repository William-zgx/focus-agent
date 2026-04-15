"""Compatibility shim.

Canonical import:
    from focus_agent.observability.tracing import (
        build_invoke_config,
        build_trace_metadata,
        build_trace_tags,
    )
"""

from .observability.tracing import build_invoke_config, build_trace_metadata, build_trace_tags

__all__ = [
    "build_invoke_config",
    "build_trace_metadata",
    "build_trace_tags",
]
