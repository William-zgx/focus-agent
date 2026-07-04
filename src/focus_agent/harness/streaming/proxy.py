"""Client-side stream optimization proxy.

When a long-lived SSE connection is serving a browser, every event repeats
identical envelope fields (``run_id``, ``thread_id``, ``turn_id``,
``source_node``) because they are produced by
:func:`focus_agent.harness.streaming.protocol.canonical_event_payload`. For
bandwidth-sensitive clients (mobile, high-latency links), that waste adds up
quickly. This proxy sits between the bridge and the SSE serializer and can:

* Strip redundant envelope fields once they've been observed for a run.
* Collapse no-op / empty heartbeats when the client does not need them.
* Drop duplicate deltas that would re-emit text already sent.

The proxy is deliberately **opt-in**: by default it is a pass-through and does
nothing. It is enabled either by constructing it with non-default config, or
by passing ``?optimize_stream=true`` from the API layer.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .bridge import END_SENTINEL, HEARTBEAT_SENTINEL, StreamEvent

# The envelope fields canonical_event_payload attaches to every event.
_ENVELOPE_FIELDS = ("run_id", "thread_id", "turn_id", "source_node")


@dataclass(slots=True)
class StreamProxyConfig:
    """Toggles for :class:`StreamProxy`.

    All flags default to ``False`` so that constructing a proxy with no
    arguments preserves current wire format.
    """

    # Drop run_id/thread_id/turn_id/source_node from every event after the
    # first event (where they are preserved so the client can learn them).
    strip_redundant_fields: bool = False

    # Drop empty heartbeats entirely. Useful for transports that do their
    # own keepalive (HTTP/2, websockets, ...).
    drop_empty_heartbeats: bool = False

    # If the same (event, content) pair is emitted twice in a row, drop the
    # second copy. This guards against double-publish bugs in the producer.
    deduplicate_consecutive: bool = True

    # Optional predicate ``(event_name, data) -> bool`` that returns True when
    # the event should be forwarded. Useful for feature flags.
    should_forward: Callable[[str, Any], bool] | None = None


@dataclass(slots=True)
class StreamProxy:
    """Stateful, per-subscription event transformer.

    Instances are **not** thread safe and should not be shared across
    concurrent subscribers.
    """

    config: StreamProxyConfig = field(default_factory=StreamProxyConfig)

    # Internal state ---------------------------------------------------------
    _envelope_seen: dict[str, Any] = field(default_factory=dict, init=False)
    _last_key: tuple[str, str] | None = field(default=None, init=False)

    # ------------------------------------------------------------------ API
    def reset(self) -> None:
        """Reset internal state. Call before reusing a proxy for a new run."""
        self._envelope_seen.clear()
        self._last_key = None

    def process_event(self, event: Any) -> Any | None:
        """Transform a single stream event.

        Accepts either a :class:`StreamEvent` or the raw sentinels
        (``HEARTBEAT_SENTINEL`` / ``END_SENTINEL``). Returns the event to
        forward (possibly mutated), or ``None`` to drop it.
        """
        # Pass the sentinels through untouched (or drop heartbeats if configured).
        if event is END_SENTINEL:
            return event
        if event is HEARTBEAT_SENTINEL:
            if self.config.drop_empty_heartbeats:
                return None
            return event

        event_name = getattr(event, "event", None)
        data = getattr(event, "data", None)

        # Allow callers to inject a feature-flag filter.
        if self.config.should_forward is not None:
            try:
                if not self.config.should_forward(event_name, data):
                    return None
            except Exception:  # noqa: BLE001 - never break the stream
                pass

        # Heartbeats that aren't the sentinel (e.g. explicit heartbeat events
        # published over the bridge) can be dropped too.
        if self.config.drop_empty_heartbeats and event_name == "heartbeat":
            return None

        if isinstance(data, dict):
            data = self._process_data(event_name, data)
            if is_dropped(data):
                return None
            # Mutate in place if the event object allows it; otherwise wrap.
            try:
                event.data = data
            except Exception:  # noqa: BLE001
                # StreamEvent is a frozen dataclass; create a replacement.
                if isinstance(event, StreamEvent):
                    event = StreamEvent(id=event.id, event=event.event, data=data)
        return event

    # ------------------------------------------------------------ internals
    def _process_data(self, event_name: str, data: dict[str, Any]) -> dict[str, Any]:
        # Optionally deduplicate consecutive identical events. Compute the
        # fingerprint on the *original* data (before envelope stripping) so
        # that the first event (with envelope) and the second event (without)
        # are still recognised as duplicates when their payload matches.
        if self.config.deduplicate_consecutive:
            dedup_payload = {k: v for k, v in data.items() if k not in _ENVELOPE_FIELDS}
            key = (event_name, _stable_fingerprint(dedup_payload))
            if key == self._last_key and event_name in {
                "message.delta",
                "reasoning.delta",
                "heartbeat",
            }:
                return _DROP
            self._last_key = key

        # Optionally strip redundant envelope fields.
        if self.config.strip_redundant_fields:
            data = self._strip_envelope(data)

        return data

    def _strip_envelope(self, data: dict[str, Any]) -> dict[str, Any]:
        # First event for a given run preserves the envelope.
        if not self._envelope_seen:
            for field_name in _ENVELOPE_FIELDS:
                if field_name in data:
                    self._envelope_seen[field_name] = data[field_name]
            return data
        # Strip fields that match what we've already sent.
        changed = False
        result: dict[str, Any] = {}
        for key, value in data.items():
            if key in _ENVELOPE_FIELDS:
                if self._envelope_seen.get(key) == value:
                    changed = True
                    continue
                # Value changed (e.g. new run) — re-seed and include.
                self._envelope_seen[key] = value
            result[key] = value
        return result if changed else data


def _stable_fingerprint(value: Any) -> str:
    """Best-effort fingerprint for dedup. Falls back to ``str`` for unknowns."""
    try:
        import json

        return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        return str(value)


# Internal sentinel returned from _process_data when the event should be dropped.
class _Drop:
    __slots__ = ()


_DROP = _Drop()


def is_dropped(data: Any) -> bool:
    """Return True when ``data`` is the internal drop marker from proxy."""
    return isinstance(data, _Drop)


__all__ = [
    "StreamProxy",
    "StreamProxyConfig",
    "is_dropped",
]
