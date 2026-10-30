"""Shared inputs handed to every default ``build_*_tools`` factory."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import common as _common


# Resolvers look up ``common`` at call time so tests patch a single place:
# ``focus_agent.capabilities.default_tool_modules.common``.
def _resolve_thread_id() -> str | None:
    return _common._get_current_thread_id()


def _resolve_branch_id() -> str | None:
    return _common._get_current_branch_id()


def _resolve_user_id() -> str | None:
    return _common._get_current_user_id()


@dataclass(frozen=True, slots=True)
class ToolBuildContext:
    workspace_root: Path
    tool_catalog: Any
    emit_tool_event: Callable[..., None]
    memory_embedding_service: Any = None
    retrieval_index: Any = None
    # Persists oversized tool output so it can be re-read via tool-observation:// refs.
    save_tool_observation: Callable[..., str | None] | None = None
    get_current_thread_id: Callable[[], str | None] = _resolve_thread_id
    get_current_branch_id: Callable[[], str | None] = _resolve_branch_id
    get_current_user_id: Callable[[], str | None] = _resolve_user_id


__all__ = ["ToolBuildContext"]
