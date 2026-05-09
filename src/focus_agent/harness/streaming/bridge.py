from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
import logging
import time
from typing import Any

logger = logging.getLogger("focus_agent.harness.streaming")


@dataclass(frozen=True, slots=True)
class StreamEvent:
    """Single event emitted by a harness run."""

    id: str
    event: str
    data: Any

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "event": self.event, "data": self.data}


HEARTBEAT_SENTINEL = StreamEvent(id="", event="__heartbeat__", data=None)
END_SENTINEL = StreamEvent(id="", event="__end__", data=None)


@dataclass(slots=True)
class _RunStream:
    events: list[StreamEvent] = field(default_factory=list)
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    ended: bool = False
    start_offset: int = 0


class InMemoryStreamBridge:
    """Bounded in-process event log for run streaming.

    Producers call :meth:`publish`; consumers iterate :meth:`subscribe`.
    Retained events allow late or reconnecting consumers to replay from the
    earliest retained event or from a matching ``last_event_id``.
    """

    def __init__(
        self,
        *,
        queue_maxsize: int | None = None,
        max_buffer_size: int | None = None,
    ) -> None:
        buffer_size = queue_maxsize if queue_maxsize is not None else max_buffer_size
        if buffer_size is None:
            buffer_size = 256
        if buffer_size < 1:
            raise ValueError("queue_maxsize must be at least 1")
        self._maxsize = buffer_size
        self._streams: dict[str, _RunStream] = {}
        self._counters: dict[str, int] = {}

    async def publish(self, run_id: str, event: str, data: Any) -> StreamEvent:
        stream = self._get_or_create_stream(run_id)
        entry = StreamEvent(id=self._next_id(run_id), event=event, data=data)
        async with stream.condition:
            stream.events.append(entry)
            self._trim(stream)
            stream.condition.notify_all()
        return entry

    async def publish_event(self, run_id: str, event: StreamEvent) -> StreamEvent:
        stream = self._get_or_create_stream(run_id)
        async with stream.condition:
            stream.events.append(event)
            self._trim(stream)
            stream.condition.notify_all()
        return event

    async def publish_end(self, run_id: str) -> None:
        stream = self._get_or_create_stream(run_id)
        async with stream.condition:
            stream.ended = True
            stream.condition.notify_all()

    async def subscribe(
        self,
        run_id: str,
        *,
        last_event_id: str | None = None,
        heartbeat_interval: float = 15.0,
    ) -> AsyncIterator[StreamEvent]:
        stream = self._get_or_create_stream(run_id)
        async with stream.condition:
            next_offset = self._resolve_start_offset(stream, last_event_id)

        while True:
            async with stream.condition:
                if next_offset < stream.start_offset:
                    logger.warning(
                        "Subscriber for run %s fell behind retained stream buffer",
                        run_id,
                    )
                    next_offset = stream.start_offset

                local_index = next_offset - stream.start_offset
                if 0 <= local_index < len(stream.events):
                    entry = stream.events[local_index]
                    next_offset += 1
                elif stream.ended:
                    entry = END_SENTINEL
                else:
                    try:
                        await asyncio.wait_for(
                            stream.condition.wait(),
                            timeout=max(float(heartbeat_interval), 0.0),
                        )
                    except TimeoutError:
                        entry = HEARTBEAT_SENTINEL
                    else:
                        continue

            yield entry
            if entry is END_SENTINEL:
                return

    async def snapshot(self, run_id: str) -> list[StreamEvent]:
        stream = self._streams.get(run_id)
        if stream is None:
            return []
        async with stream.condition:
            return list(stream.events)

    async def stream_ended(self, run_id: str) -> bool | None:
        stream = self._streams.get(run_id)
        if stream is None:
            return None
        async with stream.condition:
            return stream.ended

    async def cleanup(self, run_id: str, *, delay: float = 0.0) -> None:
        if delay > 0:
            await asyncio.sleep(delay)
        self._streams.pop(run_id, None)
        self._counters.pop(run_id, None)

    async def close(self) -> None:
        self._streams.clear()
        self._counters.clear()

    def _get_or_create_stream(self, run_id: str) -> _RunStream:
        if run_id not in self._streams:
            self._streams[run_id] = _RunStream()
            self._counters[run_id] = 0
        return self._streams[run_id]

    def _next_id(self, run_id: str) -> str:
        self._counters[run_id] = self._counters.get(run_id, 0) + 1
        timestamp_ms = int(time.time() * 1000)
        sequence = self._counters[run_id] - 1
        return f"{timestamp_ms}-{sequence}"

    def _trim(self, stream: _RunStream) -> None:
        if len(stream.events) <= self._maxsize:
            return
        overflow = len(stream.events) - self._maxsize
        del stream.events[:overflow]
        stream.start_offset += overflow

    def _resolve_start_offset(self, stream: _RunStream, last_event_id: str | None) -> int:
        if last_event_id is None:
            return stream.start_offset
        for index, event in enumerate(stream.events):
            if event.id == last_event_id:
                return stream.start_offset + index + 1
        if stream.events:
            logger.warning(
                "last_event_id=%s not found in retained buffer; replaying from earliest event",
                last_event_id,
            )
        return stream.start_offset


MemoryStreamBridge = InMemoryStreamBridge


__all__ = [
    "END_SENTINEL",
    "HEARTBEAT_SENTINEL",
    "InMemoryStreamBridge",
    "MemoryStreamBridge",
    "StreamEvent",
]
