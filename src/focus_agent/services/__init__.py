from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .branches import BranchService
    from .chat import ChatService


def __getattr__(name: str) -> Any:
    if name == "BranchService":
        from .branches import BranchService

        return BranchService
    if name == "ChatService":
        from .chat import ChatService

        return ChatService
    raise AttributeError(name)

__all__ = ["BranchService", "ChatService"]
