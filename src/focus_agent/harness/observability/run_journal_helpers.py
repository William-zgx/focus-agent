from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TypeVar

from focus_agent.core.repo_call import has_repo_method
from focus_agent.observability.trajectory import TrajectoryStep

from ..streaming import InMemoryStreamBridge, StreamEvent

if TYPE_CHECKING:
    from .run_journal import JournalEvent, JournalRun, JournalToolEvent, RunJournal

T = TypeVar("T")


TOOL_EVENT_NAMES = frozenset(
    {
        "tool.call.delta",
        "tool.requested",
        "tool.result",
        "tool.error",
    }
)


def trajectory_summary_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    return _trajectory_summary(snapshot)


def _snapshot(
    run: JournalRun | None,
    events: Iterable[JournalEvent],
    tool_events: Iterable[JournalToolEvent],
) -> dict[str, Any]:
    event_dicts = [event.to_dict() for event in events]
    tool_dicts = [event.to_dict() for event in tool_events]
    return {
        "run": run.to_dict() if run is not None else None,
        "events": event_dicts,
        "tool_events": tool_dicts,
        "counts": {
            "events": len(event_dicts),
            "tool_events": len(tool_dicts),
        },
    }


def _journal_replay_start(events: list[JournalEvent], last_event_id: str | None) -> int:
    if last_event_id is None:
        return 0
    for index, event in enumerate(events):
        if event.stream_event_id == last_event_id or event.event_id == last_event_id:
            return index + 1
    return 0


def _stream_event_from_journal_event(event: JournalEvent) -> StreamEvent:
    return StreamEvent(
        id=event.stream_event_id or event.event_id,
        event=event.event,
        data=event.data,
    )


async def _journal_run_is_terminal(journal: RunJournal, run_id: str) -> bool:
    if not has_repo_method(journal, "get_run"):
        return False
    run = await journal.get_run(run_id)
    if run is None:
        return False
    status = getattr(run, "status", None)
    return str(status) in {"success", "error", "timeout", "interrupted"}


async def _bridge_stream_ended(bridge: InMemoryStreamBridge, run_id: str) -> bool | None:
    if not has_repo_method(bridge, "stream_ended"):
        return None
    return await bridge.stream_ended(run_id)


def _trajectory_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    run = snapshot.get("run") or {}
    tool_events = list(snapshot.get("tool_events") or [])
    steps: list[dict[str, Any]] = []
    for event in tool_events:
        if event.get("status") not in {"result", "error"}:
            continue
        steps.append(
            TrajectoryStep(
                tool=str(event.get("tool_name") or "unknown_tool"),
                args=dict(event.get("args") or {}),
                observation=_observation_text(event),
                duration_ms=float(event.get("duration_ms") or 0.0),
                error=str(event["error"]) if event.get("error") else None,
            ).to_dict()
        )
    return {
        "id": run.get("run_id"),
        "kind": "harness_run",
        "status": run.get("status", "unknown"),
        "thread_id": run.get("thread_id"),
        "trajectory": steps,
        "metrics": {
            "events": (snapshot.get("counts") or {}).get("events", 0),
            "tool_calls": len(steps),
        },
        "error": run.get("error"),
    }


def _tool_event_from_journal_event(event: JournalEvent) -> JournalToolEvent | None:
    if event.event not in TOOL_EVENT_NAMES:
        return None
    from .run_journal import JournalToolEvent

    data = event.data
    tool_name = _first_str(data, "tool_name", "name", "tool")
    status = _tool_status(event.event)
    return JournalToolEvent(
        event_id=event.event_id,
        run_id=event.run_id,
        tool_call_id=_first_str(data, "tool_call_id", "call_id", "id"),
        tool_name=tool_name,
        status=status,
        sequence=event.sequence,
        args=dict(data.get("args") or data.get("arguments") or {}),
        result=data.get("result") if "result" in data else data.get("observation"),
        error=_first_str(data, "error"),
        duration_ms=_optional_float(data.get("duration_ms")),
        metadata={key: value for key, value in data.items() if key not in _TOOL_PAYLOAD_KEYS},
        created_at=event.created_at,
    )


def _tool_status(event: str) -> str:
    if event == "tool.requested":
        return "requested"
    if event == "tool.error":
        return "error"
    if event == "tool.result":
        return "result"
    return "delta"


def _observation_text(event: dict[str, Any]) -> str:
    if event.get("error"):
        return str(event["error"])
    result = event.get("result")
    if isinstance(result, str):
        return result
    if result is None:
        return ""
    return _json_dumps(result)


def _replace_run(run: JournalRun, **changes: Any) -> JournalRun:
    from .run_journal import JournalRun

    values = run.to_dict()
    values.update(changes)
    return JournalRun(**values)


def _row_to_run(row: sqlite3.Row) -> JournalRun:
    from .run_journal import JournalRun

    return JournalRun(
        run_id=row["run_id"],
        thread_id=row["thread_id"],
        assistant_id=row["assistant_id"],
        user_id=row["user_id"],
        status=row["status"],
        on_disconnect=row["on_disconnect"] if "on_disconnect" in row.keys() else "cancel",
        multitask_strategy=row["multitask_strategy"],
        metadata=_json_loads(row["metadata_json"]),
        kwargs=_json_loads(row["kwargs_json"]),
        error=row["error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completion=_json_loads(row["completion_json"]),
    )


def _row_to_event(row: sqlite3.Row) -> JournalEvent:
    from .run_journal import JournalEvent

    return JournalEvent(
        event_id=row["event_id"],
        run_id=row["run_id"],
        event=row["event"],
        data=_json_loads(row["data_json"]),
        sequence=int(row["sequence"]),
        stream_event_id=row["stream_event_id"],
        created_at=row["created_at"],
    )


def _row_to_tool_event(row: sqlite3.Row) -> JournalToolEvent:
    from .run_journal import JournalToolEvent

    return JournalToolEvent(
        event_id=row["event_id"],
        run_id=row["run_id"],
        tool_call_id=row["tool_call_id"],
        tool_name=row["tool_name"],
        status=row["status"],
        sequence=int(row["sequence"]),
        args=_json_loads(row["args_json"]),
        result=_json_loads_any(row["result_json"]),
        error=row["error"],
        duration_ms=row["duration_ms"],
        metadata=_json_loads(row["metadata_json"]),
        created_at=row["created_at"],
    )


def _limit(items: list[T], limit: int | None) -> list[T]:
    if limit is None:
        return items
    return items[: max(int(limit), 0)]


def _next_sequence(events: list[JournalEvent]) -> int:
    if not events:
        return 1
    return max(event.sequence for event in events) + 1


def _dict_data(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        return _copy_json(data)
    return {"value": _copy_json(data)}


def _first_str(data: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if value is not None:
            return str(value)
    return None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _copy_json(value: T) -> T:
    return json.loads(_json_dumps(value))


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    loaded = json.loads(value)
    return loaded if isinstance(loaded, dict) else {"value": loaded}


def _json_loads_any(value: str | None) -> Any:
    if not value:
        return None
    return json.loads(value)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _event_id() -> str:
    return str(uuid.uuid4())


_TOOL_PAYLOAD_KEYS = {
    "args",
    "arguments",
    "call_id",
    "duration_ms",
    "error",
    "id",
    "name",
    "observation",
    "result",
    "tool",
    "tool_call_id",
    "tool_name",
}


__all__ = [
    "TOOL_EVENT_NAMES",
    "trajectory_summary_from_snapshot",
]
