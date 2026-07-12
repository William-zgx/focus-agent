from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
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
        cleanup_delay_seconds: float = 60.0,
    ) -> None:
        buffer_size = queue_maxsize if queue_maxsize is not None else max_buffer_size
        if buffer_size is None:
            buffer_size = 256
        if buffer_size < 1:
            raise ValueError("queue_maxsize must be at least 1")
        cleanup_delay = float(cleanup_delay_seconds)
        if not math.isfinite(cleanup_delay) or cleanup_delay < 0:
            raise ValueError("cleanup_delay_seconds must be a finite non-negative number")
        self._maxsize = buffer_size
        self._cleanup_delay_seconds = cleanup_delay
        self._streams: dict[str, _RunStream] = {}
        self._counters: dict[str, int] = {}
        self._cleanup_tasks: dict[str, asyncio.Task[None]] = {}
        self._state_lock = asyncio.Lock()
        self._shutdown = False

    async def publish(self, run_id: str, event: str, data: Any) -> StreamEvent:
        async with self._state_lock:
            stream = self._get_or_create_stream_locked(run_id)
            entry = StreamEvent(id=self._next_id_locked(run_id), event=event, data=data)
            async with stream.condition:
                stream.events.append(entry)
                self._trim(stream)
                if event == "run.closed":
                    stream.ended = True
                stream.condition.notify_all()
            if event == "run.closed":
                self._schedule_cleanup_locked(run_id, stream)
        return entry

    async def publish_event(self, run_id: str, event: StreamEvent) -> StreamEvent:
        async with self._state_lock:
            stream = self._get_or_create_stream_locked(run_id)
            async with stream.condition:
                stream.events.append(event)
                self._trim(stream)
                if event.event == "run.closed":
                    stream.ended = True
                stream.condition.notify_all()
            if event.event == "run.closed":
                self._schedule_cleanup_locked(run_id, stream)
        return event

    async def publish_end(self, run_id: str) -> None:
        async with self._state_lock:
            if self._shutdown:
                return
            stream = self._get_or_create_stream_locked(run_id)
            async with stream.condition:
                stream.ended = True
                stream.condition.notify_all()
            self._schedule_cleanup_locked(run_id, stream)

    async def subscribe(
        self,
        run_id: str,
        *,
        last_event_id: str | None = None,
        heartbeat_interval: float = 15.0,
    ) -> AsyncIterator[StreamEvent]:
        async with self._state_lock:
            if self._shutdown:
                stream = None
            else:
                stream = self._get_or_create_stream_locked(run_id)
        if stream is None:
            yield END_SENTINEL
            return
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
        async with self._state_lock:
            stream = self._streams.get(run_id)
        if stream is None:
            return []
        async with stream.condition:
            return list(stream.events)

    async def stream_ended(self, run_id: str) -> bool | None:
        async with self._state_lock:
            stream = self._streams.get(run_id)
        if stream is None:
            return None
        async with stream.condition:
            return stream.ended

    async def cleanup(self, run_id: str, *, delay: float = 0.0) -> None:
        async with self._state_lock:
            stream = self._streams.get(run_id)
        if delay > 0:
            await asyncio.sleep(delay)
        await self._remove_stream(run_id, stream)

    async def close(self) -> None:
        await self._close(permanent=False)

    async def shutdown(self) -> None:
        await self._close(permanent=True)

    async def _close(self, *, permanent: bool) -> None:
        async with self._state_lock:
            if permanent:
                self._shutdown = True
            streams = list(self._streams.values())
            cleanup_tasks = list(self._cleanup_tasks.values())
            self._streams.clear()
            self._counters.clear()
            self._cleanup_tasks.clear()

        for task in cleanup_tasks:
            task.cancel()
        for stream in streams:
            async with stream.condition:
                stream.ended = True
                stream.condition.notify_all()
        if cleanup_tasks:
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)

    async def _remove_stream(self, run_id: str, stream: _RunStream | None) -> None:
        current_task = asyncio.current_task()
        cleanup_task: asyncio.Task[None] | None = None
        async with self._state_lock:
            removed = False
            if stream is not None and self._streams.get(run_id) is stream:
                self._streams.pop(run_id, None)
                self._counters.pop(run_id, None)
                removed = True
            scheduled = self._cleanup_tasks.get(run_id)
            if removed and scheduled is not None and scheduled is not current_task:
                cleanup_task = self._cleanup_tasks.pop(run_id)

        if cleanup_task is not None:
            cleanup_task.cancel()
            await asyncio.gather(cleanup_task, return_exceptions=True)

    async def _cleanup_after_delay(self, run_id: str, stream: _RunStream) -> None:
        current_task = asyncio.current_task()
        try:
            if self._cleanup_delay_seconds > 0:
                await asyncio.sleep(self._cleanup_delay_seconds)
            async with self._state_lock:
                if self._cleanup_tasks.get(run_id) is not current_task:
                    return
                self._cleanup_tasks.pop(run_id, None)
                if self._streams.get(run_id) is stream:
                    self._streams.pop(run_id, None)
                    self._counters.pop(run_id, None)
        except asyncio.CancelledError:
            async with self._state_lock:
                if self._cleanup_tasks.get(run_id) is current_task:
                    self._cleanup_tasks.pop(run_id, None)
            raise

    def _schedule_cleanup_locked(self, run_id: str, stream: _RunStream) -> None:
        task = self._cleanup_tasks.get(run_id)
        if task is not None and not task.done():
            return
        self._cleanup_tasks[run_id] = asyncio.create_task(
            self._cleanup_after_delay(run_id, stream),
            name=f"stream-cleanup:{run_id}",
        )

    def _get_or_create_stream_locked(self, run_id: str) -> _RunStream:
        if self._shutdown:
            raise RuntimeError("stream bridge is shut down")
        if run_id not in self._streams:
            self._streams[run_id] = _RunStream()
            self._counters[run_id] = 0
        return self._streams[run_id]

    def _next_id_locked(self, run_id: str) -> str:
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
