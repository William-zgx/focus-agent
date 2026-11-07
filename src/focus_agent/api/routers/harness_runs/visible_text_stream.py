"""Per-message visible text buffering for one run's live stream."""

from __future__ import annotations

from focus_agent.transport.stream_events import safe_stream_visible_text_transition


class VisibleTextStream:
    """Filters each model message on its own and joins messages with a paragraph break.

    A tool-calling preamble must neither leak into the next message's filter
    state nor stand in for the final answer.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._pending = ""
        self._message_id: str | None = None
        self._separator_pending = False
        self._tool_call_message_ids: set[str] = set()

    def note_tool_call(self, message_id: str) -> None:
        self._tool_call_message_ids.add(message_id)

    def drop_pending(self) -> None:
        self._pending = ""

    def push(self, message_id: str, delta: str) -> str:
        """Return the text to publish for ``delta``; empty while it is held back."""
        if message_id != self._message_id:
            self._separator_pending = self._separator_pending or bool(self._buffer)
            self._buffer = ""
            self._pending = ""
            self._message_id = message_id
        next_text, self._pending = safe_stream_visible_text_transition(
            self._buffer, delta, pending_text=self._pending
        )
        if next_text.startswith(self._buffer):
            publish = next_text[len(self._buffer) :]
        else:
            publish = next_text
        self._buffer = next_text
        if publish and self._separator_pending:
            publish = f"\n\n{publish}"
            self._separator_pending = False
        return publish

    def completed_fallback_text(self) -> str:
        """Text of the last message, unless that message called tools."""
        if self._message_id in self._tool_call_message_ids:
            return ""
        return self._buffer


__all__ = ["VisibleTextStream"]
