from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from ..streaming import END_SENTINEL, InMemoryStreamBridge, StreamEvent
from .run_journal_helpers import (
    _bridge_stream_ended,
    _journal_replay_start,
    _journal_run_is_terminal,
    _stream_event_from_journal_event,
)

if TYPE_CHECKING:
    from .run_journal import RunJournal


class JournaledStreamBridge:
    """Bridge wrapper that persists every published stream event into a run journal."""

    def __init__(
        self,
        journal: RunJournal,
        bridge: InMemoryStreamBridge | None = None,
    ) -> None:
        self.journal = journal
        self.bridge = bridge or InMemoryStreamBridge()

    async def publish(self, run_id: str, event: str, data: Any) -> StreamEvent:
        entry = await self.bridge.publish(run_id, event, data)
        await self.journal.append_stream_event(run_id, entry)
        return entry

    async def publish_event(self, run_id: str, event: StreamEvent) -> StreamEvent:
        entry = await self.bridge.publish_event(run_id, event)
        await self.journal.append_stream_event(run_id, entry)
        return entry

    async def publish_end(self, run_id: str) -> None:
        await self.bridge.publish_end(run_id)

    async def subscribe(
        self,
        run_id: str,
        *,
        last_event_id: str | None = None,
        heartbeat_interval: float = 15.0,
    ) -> AsyncIterator[StreamEvent]:
        yielded_ids: set[str] = set()
        history = await self.journal.list_events(run_id)
        replay_start = _journal_replay_start(history, last_event_id)
        replay_events = history[replay_start:]
        bridge_last_event_id = last_event_id

        for event in replay_events:
            stream_event = _stream_event_from_journal_event(event)
            yielded_ids.add(stream_event.id)
            bridge_last_event_id = stream_event.id
            yield stream_event

        if history and history[-1].event == "run.closed":
            yield END_SENTINEL
            return
        bridge_ended = await _bridge_stream_ended(self.bridge, run_id)
        if await _journal_run_is_terminal(self.journal, run_id) and bridge_ended is not False:
            yield END_SENTINEL
            return

        async for event in self.bridge.subscribe(
            run_id,
            last_event_id=bridge_last_event_id,
            heartbeat_interval=heartbeat_interval,
        ):
            if event is END_SENTINEL:
                yield event
                return
            if event.id and event.id in yielded_ids:
                continue
            if event.id:
                yielded_ids.add(event.id)
            yield event

    def __getattr__(self, name: str) -> Any:
        return getattr(self.bridge, name)


__all__ = ["JournaledStreamBridge"]
