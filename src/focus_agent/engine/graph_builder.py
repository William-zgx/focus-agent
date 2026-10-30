"""Compatibility shim for legacy graph builder imports."""

from ..model_registry import create_chat_model
from .graph.builder import *  # noqa: F401,F403
from .graph.builder import __all__ as _builder_all

__all__ = [*_builder_all, "create_chat_model"]
