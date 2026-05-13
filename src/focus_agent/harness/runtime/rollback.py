from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from focus_agent.core.repo_call import has_repo_method

ROLLBACK_TARGET_METADATA_KEY = "harness.rollback_target"


@dataclass(slots=True)
class CheckpointRollbackTarget:
    """Checkpoint state captured before a run mutates a thread."""

    thread_id: str
    checkpoint_ns: str
    checkpoint_id: str | None
    metadata: dict[str, Any]

    def to_metadata(self) -> dict[str, str | None]:
        return {
            "thread_id": self.thread_id,
            "checkpoint_ns": self.checkpoint_ns,
            "checkpoint_id": self.checkpoint_id,
        }


@dataclass(frozen=True, slots=True)
class CheckpointRollbackResult:
    applied: bool = False
    requested: bool = True
    reason: str | None = None
    checkpoint_id: str | None = None
    error: str | None = None
    partial: bool = False
    unreverted_scopes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested": self.requested,
            "applied": self.applied,
            "reason": self.reason,
            "checkpoint_id": self.checkpoint_id,
            "error": self.error,
            "partial": self.partial,
            "unreverted_scopes": list(self.unreverted_scopes),
        }


RollbackHandler = Callable[[Any], Awaitable[CheckpointRollbackResult | None]]


def capture_checkpoint_rollback_target(graph: Any, thread_id: str) -> CheckpointRollbackTarget:
    """Capture the current thread checkpoint before a harness run starts."""

    snapshot = graph.get_state({"configurable": {"thread_id": thread_id}})
    config = dict(getattr(snapshot, "config", {}) or {})
    configurable = dict(config.get("configurable") or {})
    checkpoint_ns = str(configurable.get("checkpoint_ns") or "")
    checkpoint_id = configurable.get("checkpoint_id")
    return CheckpointRollbackTarget(
        thread_id=thread_id,
        checkpoint_ns=checkpoint_ns,
        checkpoint_id=str(checkpoint_id) if checkpoint_id else None,
        metadata=dict(getattr(snapshot, "metadata", {}) or {}),
    )


async def restore_graph_rollback_target(
    graph: Any,
    checkpointer: Any | None,
    target: CheckpointRollbackTarget | None,
) -> CheckpointRollbackResult:
    """Restore a thread to a previously captured checkpoint target."""

    if target is None:
        return CheckpointRollbackResult(requested=True, applied=False, reason="missing_rollback_target")
    return await asyncio.to_thread(_restore_graph_rollback_target_sync, graph, checkpointer, target)


def rollback_handler_for_graph(graph: Any, checkpointer: Any | None = None) -> RollbackHandler:
    async def handler(record: Any) -> CheckpointRollbackResult:
        return await restore_graph_rollback_target(
            graph,
            checkpointer,
            getattr(record, "rollback_target", None),
        )

    return handler


def _restore_graph_rollback_target_sync(
    graph: Any,
    checkpointer: Any | None,
    target: CheckpointRollbackTarget,
) -> CheckpointRollbackResult:
    if target.checkpoint_id is None:
        if checkpointer is None:
            return CheckpointRollbackResult(requested=True, applied=False, reason="missing_checkpointer")
        if not has_repo_method(checkpointer, "delete_thread"):
            return CheckpointRollbackResult(requested=True, applied=False, reason="delete_thread_unavailable")
        checkpointer.delete_thread(target.thread_id)
        return CheckpointRollbackResult(requested=True, applied=True, reason="deleted_thread")

    if not has_repo_method(graph, "update_state"):
        return CheckpointRollbackResult(requested=True, applied=False, reason="update_state_unavailable")
    config = {
        "configurable": {
            "thread_id": target.thread_id,
            "checkpoint_ns": target.checkpoint_ns,
            "checkpoint_id": target.checkpoint_id,
        }
    }
    next_config = graph.update_state(config, [], as_node="__copy__")
    checkpoint_id = None
    if isinstance(next_config, dict):
        checkpoint_id = str(next_config.get("configurable", {}).get("checkpoint_id") or "") or None
    return CheckpointRollbackResult(requested=True, applied=True, checkpoint_id=checkpoint_id)


__all__ = [
    "CheckpointRollbackResult",
    "CheckpointRollbackTarget",
    "ROLLBACK_TARGET_METADATA_KEY",
    "RollbackHandler",
    "capture_checkpoint_rollback_target",
    "restore_graph_rollback_target",
    "rollback_handler_for_graph",
]
