"""High level lifecycle publisher for harness streaming events.

The low level :class:`~focus_agent.harness.streaming.bridge.InMemoryStreamBridge`
only knows how to blindly emit ``(event, data)`` pairs. The rest of the code
base (especially ``_produce_run_stream`` in ``replay_streaming.py``) manually
sequences deltas, completion markers and lifecycle transitions on top of it.

This module wraps that low level bridge with a small typed façade so that
producers can call lifecycle-aware hooks (``on_assistant_text_delta``,
``on_tool_call_started``, ``on_turn_completed`` ...) without having to track
counters, sequence numbers, or payload shapes themselves.

The publisher is *fail soft*: any exception raised by the underlying bridge is
caught and logged, so a misbehaving observer can never crash the run.  A
``fatal`` flag is recorded on the publisher so callers can detect failure and
fall back to direct publishing if desired.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .protocol import canonical_event_payload

logger = logging.getLogger("focus_agent.harness.streaming.publisher")


@dataclass(slots=True)
class AgentEventPublisher:
    """Publishes lifecycle-aware events for a single run to the stream bridge.

    Parameters
    ----------
    bridge:
        The stream bridge (anything with an async ``publish(run_id, event, data)``
        method; typically an ``InMemoryStreamBridge`` or ``JournaledStreamBridge``).
    run_id, thread_id:
        Identifiers for the run being published; attached to every payload.
    source_node:
        Default ``source_node`` field attached to payloads.
    """

    bridge: Any
    run_id: str
    thread_id: str
    source_node: str = "harness"
    _sequence: int = field(default=0, init=False)
    failed: bool = field(default=False, init=False)
    _closed: bool = field(default=False, init=False)
    _close_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)

    # ------------------------------------------------------------------ state
    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    # ------------------------------------------------------------------ utils
    async def _emit(self, event: str, **payload: Any) -> None:
        """Publish a single event to the bridge in the canonical envelope."""
        data = canonical_event_payload(
            run_id=self.run_id,
            thread_id=self.thread_id,
            turn_id=self.run_id,
            sequence=self._next_sequence(),
            source_node=self.source_node,
            **payload,
        )
        try:
            await self.bridge.publish(self.run_id, event, data)
        except Exception:  # noqa: BLE001 - fail soft
            self.failed = True
            logger.warning(
                "AgentEventPublisher failed to emit %s for run %s; falling back",
                event,
                self.run_id,
                exc_info=True,
            )

    # -------------------------------------------------------------- lifecycle
    async def on_turn_started(self, **extra: Any) -> None:
        await self._emit("run.metadata", **extra)
        await self._emit("run.status", phase="running", **extra)

    async def on_turn_completed(
        self,
        status: str = "success",
        final_state: dict[str, Any] | None = None,
        *,
        close: bool = True,
        **extra: Any,
    ) -> None:
        if status == "success":
            await self._emit("run.completed", status="succeeded", final_state=final_state, **extra)
        elif status in {"error", "failed"}:
            await self._emit("run.failed", error="TurnError", final_state=final_state, **extra)
        else:
            await self._emit("run.completed", status=status, final_state=final_state, **extra)
        if close:
            await self.close()

    async def on_turn_interrupted(self, reason: str | None = None, **extra: Any) -> None:
        payload: dict[str, Any] = {"phase": "interrupted"}
        if reason:
            payload["reason"] = reason
        await self._emit("run.status", **payload, **extra)
        await self._emit("run.interrupt", **payload, **extra)
        await self.close()

    async def close(self) -> None:
        """Emit ``run.closed`` and ``publish_end`` so subscribers terminate.

        Safe to call multiple times; subsequent calls are no-ops after the first
        successful close.
        """
        if self._closed:
            return
        close_task = self._close_task
        if close_task is None:
            close_task = asyncio.create_task(
                self._close_once(),
                name=f"stream-publisher-close:{self.run_id}",
            )
            self._close_task = close_task
        await asyncio.shield(close_task)

    async def _close_once(self) -> None:
        try:
            try:
                await self._emit("run.closed", status="closed")
            except Exception:  # noqa: BLE001
                pass
            publish_end = getattr(self.bridge, "publish_end", None)
            if callable(publish_end):
                try:
                    await publish_end(self.run_id)
                except Exception:  # noqa: BLE001
                    self.failed = True
                    logger.debug("publish_end failed for run %s", self.run_id, exc_info=True)
        finally:
            self._closed = True
            self._close_task = None

    async def on_run_metadata(self, **extra: Any) -> None:
        await self._emit("run.metadata", **extra)

    async def on_heartbeat(self, **extra: Any) -> None:
        await self._emit("heartbeat", **extra)

    # ------------------------------------------------------------- assistant
    async def on_assistant_text_delta(
        self,
        delta: str,
        *,
        message_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        **extra: Any,
    ) -> None:
        if not delta:
            return
        payload: dict[str, Any] = {"delta": delta}
        if message_id:
            payload["message_id"] = message_id
        if metadata:
            payload["metadata"] = metadata
        payload.update(extra)
        await self._emit("message.delta", **payload)

    async def on_message_completed(
        self,
        content: str,
        *,
        source: str | None = None,
        **extra: Any,
    ) -> None:
        payload: dict[str, Any] = {"content": content}
        if source:
            payload["source"] = source
        payload.update(extra)
        await self._emit("message.completed", **payload)

    async def on_reasoning_delta(
        self,
        delta: str,
        *,
        message_id: str | None = None,
        **extra: Any,
    ) -> None:
        payload: dict[str, Any] = {"delta": delta}
        if message_id:
            payload["message_id"] = message_id
        payload.update(extra)
        await self._emit("reasoning.delta", **payload)

    # ------------------------------------------------------------------ tools
    async def on_tool_call_started(
        self,
        tool_call_id: str,
        tool_name: str,
        args_preview: str | dict[str, Any] | None = None,
        *,
        metadata: dict[str, Any] | None = None,
        **extra: Any,
    ) -> None:
        payload: dict[str, Any] = {
            "tool_call_id": tool_call_id,
            "name": tool_name,
        }
        if args_preview is not None:
            payload["args"] = args_preview
        if metadata:
            payload["metadata"] = metadata
        payload.update(extra)
        await self._emit("tool.requested", **payload)

    async def on_tool_call_delta(
        self,
        tool_call_id: str,
        args_delta: str | dict[str, Any] | None = None,
        *,
        tool_name: str | None = None,
        **extra: Any,
    ) -> None:
        payload: dict[str, Any] = {"tool_call_id": tool_call_id}
        if tool_name:
            payload["name"] = tool_name
        if args_delta is not None:
            payload["args_delta"] = args_delta
        payload.update(extra)
        await self._emit("tool.call.delta", **payload)

    async def on_tool_call_ended(self, tool_call_id: str, **extra: Any) -> None:
        await self._emit(
            "tool.call.delta",
            tool_call_id=tool_call_id,
            completed=True,
            **extra,
        )

    async def on_tool_result(
        self,
        tool_call_id: str,
        result: Any,
        *,
        tool_name: str | None = None,
        is_error: bool = False,
        **extra: Any,
    ) -> None:
        event = "tool.error" if is_error else "tool.result"
        payload: dict[str, Any] = {
            "tool_call_id": tool_call_id,
            "result": result,
        }
        if tool_name:
            payload["name"] = tool_name
        payload.update(extra)
        await self._emit(event, **payload)

    # ------------------------------------------------------------------ misc
    async def on_state_update(
        self,
        data: dict[str, Any] | None = None,
        *,
        metadata: dict[str, Any] | None = None,
        **extra: Any,
    ) -> None:
        payload: dict[str, Any] = {}
        if data is not None:
            payload["data"] = data
        if metadata:
            payload["metadata"] = metadata
        payload.update(extra)
        await self._emit("state.update", **payload)

    async def on_task_update(self, **payload: Any) -> None:
        await self._emit("task.update", **payload)

    async def on_custom(self, event: str, **payload: Any) -> None:
        """Emit a custom (pass-through) event. Caller is responsible for event name."""
        if not event:
            return
        await self._emit(event, **payload)

    # ---------------------------------------------------- convenience factory
    @classmethod
    def for_harness(
        cls,
        harness: Any,
        run_id: str,
        thread_id: str,
        *,
        source_node: str = "harness",
    ) -> AgentEventPublisher:
        """Build a publisher from a FocusAgentHarness-like object.

        Falls back gracefully if the harness does not expose a ``stream_bridge``
        attribute (in that case publishing is a no-op and ``failed`` will be set).
        """
        bridge = getattr(harness, "stream_bridge", None)
        return cls(bridge=bridge, run_id=run_id, thread_id=thread_id, source_node=source_node)


# --------------------------------------------------------------------- helpers
def monotonic_ms() -> int:
    return int(time.monotonic() * 1000)


__all__ = ["AgentEventPublisher", "monotonic_ms"]
