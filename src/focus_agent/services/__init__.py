from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .attention import AttentionService
    from .branches import BranchService
    from .chat import ChatService


def __getattr__(name: str) -> Any:
    if name == "AttentionService":
        from .attention import AttentionService

        return AttentionService
    if name == "BranchService":
        from .branches import BranchService

        return BranchService
    if name == "ChatService":
        from .chat import ChatService

        return ChatService
    raise AttributeError(name)


__all__ = ["AttentionService", "BranchService", "ChatService"]
