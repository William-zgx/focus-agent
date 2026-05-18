"""Compatibility shim for legacy graph builder imports."""

from ..model_registry import create_chat_model
from .graph import builder as _builder
from .graph.builder import *  # noqa: F401,F403
from .graph.builder import __all__ as _builder_all


def build_graph(*args, **kwargs):
    """Build a graph while honoring legacy monkey-patches to this shim."""

    original = _builder.create_chat_model
    _builder.create_chat_model = create_chat_model
    try:
        return _builder.build_graph(*args, **kwargs)
    finally:
        _builder.create_chat_model = original


__all__ = [*_builder_all, "create_chat_model"]
