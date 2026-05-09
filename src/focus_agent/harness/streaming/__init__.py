"""Streaming primitives for the Focus Agent harness."""

from .bridge import (
    END_SENTINEL,
    HEARTBEAT_SENTINEL,
    InMemoryStreamBridge,
    MemoryStreamBridge,
    StreamEvent,
)
from .protocol import CANONICAL_EVENTS, canonical_event_payload, sse_frame

__all__ = [
    "CANONICAL_EVENTS",
    "END_SENTINEL",
    "HEARTBEAT_SENTINEL",
    "InMemoryStreamBridge",
    "MemoryStreamBridge",
    "StreamEvent",
    "canonical_event_payload",
    "sse_frame",
]
