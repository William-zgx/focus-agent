"""Compatibility shim.

Canonical import:
    from focus_agent.capabilities.default_tools import get_default_tools
"""

from .capabilities.default_tools import get_default_tools
from .capabilities.tool_registry import build_tool_registry

__all__ = ["build_tool_registry", "get_default_tools"]
