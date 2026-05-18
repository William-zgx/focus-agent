"""Compatibility shim for legacy graph builder imports."""

from .graph.builder import *  # noqa: F401,F403
from .model_registry import create_chat_model

__all__ = [*__all__, "create_chat_model"]
