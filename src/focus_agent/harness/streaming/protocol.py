from __future__ import annotations

import json
from typing import Any


CANONICAL_EVENTS = frozenset(
    {
        "run.metadata",
        "run.status",
        "heartbeat",
        "message.delta",
        "reasoning.delta",
        "tool.call.delta",
        "tool.requested",
        "tool.result",
        "tool.error",
        "state.update",
        "task.update",
        "run.interrupt",
        "run.rollback.started",
        "run.rollback.succeeded",
        "run.rollback.failed",
        "message.completed",
        "run.completed",
        "run.failed",
        "run.closed",
    }
)


def canonical_event_payload(
    *,
    run_id: str,
    thread_id: str,
    turn_id: str,
    sequence: int,
    source_node: str | None = None,
    **payload: Any,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "thread_id": thread_id,
        "turn_id": turn_id,
        "sequence": sequence,
        "source_node": source_node or "harness",
        **payload,
    }


def sse_frame(*, event: str, data: Any, event_id: str | None = None) -> str:
    lines: list[str] = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    encoded = json.dumps(data, ensure_ascii=False, default=str)
    for line in encoded.splitlines() or [""]:
        lines.append(f"data: {line}")
    return "\n".join(lines) + "\n\n"
