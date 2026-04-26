from __future__ import annotations

from typing import Any

from ..config import Settings
from .default_tool_modules import factory as _factory

# Backward-compatible patch point used by tests and local integrations.
_get_current_thread_id = _factory._get_current_thread_id


def get_default_tools(
    settings: Settings,
    *,
    store=None,
    checkpointer=None,
    artifact_metadata_repository=None,
):
    _factory._get_current_thread_id = _get_current_thread_id
    return _factory.get_default_tools(
        settings,
        store=store,
        checkpointer=checkpointer,
        artifact_metadata_repository=artifact_metadata_repository,
    )


def __getattr__(name: str) -> Any:
    return getattr(_factory, name)


__all__ = ["get_default_tools", "_get_current_thread_id"]
