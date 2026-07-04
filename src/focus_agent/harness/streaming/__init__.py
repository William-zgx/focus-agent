"""Streaming primitives for the Focus Agent harness."""

from .bridge import (
    END_SENTINEL,
    HEARTBEAT_SENTINEL,
    InMemoryStreamBridge,
    MemoryStreamBridge,
    StreamEvent,
)
from .protocol import CANONICAL_EVENTS, canonical_event_payload, sse_frame
from .publisher import AgentEventPublisher
from .proxy import StreamProxy, StreamProxyConfig, is_dropped

__all__ = [
    "CANONICAL_EVENTS",
    "END_SENTINEL",
    "HEARTBEAT_SENTINEL",
    "InMemoryStreamBridge",
    "MemoryStreamBridge",
    "StreamEvent",
    "AgentEventPublisher",
    "StreamProxy",
    "StreamProxyConfig",
    "canonical_event_payload",
    "is_dropped",
    "sse_frame",
]
