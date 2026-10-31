"""SSE (Server-Sent Events) response helpers.

The main SSE framing lives in
:mod:`focus_agent.harness.streaming.protocol` (see ``sse_frame``). This module
wires the :class:`~focus_agent.harness.streaming.proxy.StreamProxy`
optimization into FastAPI's :class:`StreamingResponse` so callers can opt into
bandwidth-efficient streaming with a single flag.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import StreamingResponse

from focus_agent.harness.streaming import StreamProxy, StreamProxyConfig, sse_frame

SSE_MEDIA_TYPE = "text/event-stream"
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def sse_streaming_response(content: Any) -> StreamingResponse:
    return StreamingResponse(content, media_type=SSE_MEDIA_TYPE, headers=dict(SSE_HEADERS))


def _is_truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() in _TRUTHY


def should_optimize_for_request(request: Request) -> bool:
    """Return True when the request explicitly asked for optimized streaming.

    Honors (in priority order):
      * ``?optimize_stream=true`` query parameter
      * ``X-Stream-Optimize: 1|true|yes`` request header
      * ``Accept`` containing the token ``stream-optimized``
      * ``X-Stream-Optimize-Auto: 1`` together with a browser User-Agent
    """
    headers = request.headers
    return (
        _is_truthy(request.query_params.get("optimize_stream"))
        or _is_truthy(headers.get("x-stream-optimize"))
        or "stream-optimized" in (headers.get("accept") or "").lower()
        or (
            _is_truthy(headers.get("x-stream-optimize-auto"))
            and (headers.get("user-agent") or "").lower().startswith("mozilla/")
        )
    )


def build_stream_proxy(request: Request) -> StreamProxy | None:
    """Build a StreamProxy for ``request`` if optimization is requested."""
    if not should_optimize_for_request(request):
        return None
    return StreamProxy(
        StreamProxyConfig(
            strip_redundant_fields=True,
            drop_empty_heartbeats=False,
            deduplicate_consecutive=True,
        )
    )


__all__ = [
    "SSE_HEADERS",
    "SSE_MEDIA_TYPE",
    "build_stream_proxy",
    "should_optimize_for_request",
    "sse_frame",
    "sse_streaming_response",
]
