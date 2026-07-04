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

from focus_agent.harness.streaming import (
    END_SENTINEL,
    HEARTBEAT_SENTINEL,
    StreamProxy,
    StreamProxyConfig,
    sse_frame,
)

SSE_MEDIA_TYPE = "text/event-stream"
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def sse_streaming_response(content: Any) -> StreamingResponse:
    return StreamingResponse(content, media_type=SSE_MEDIA_TYPE, headers=dict(SSE_HEADERS))


def should_optimize_for_request(request: Request) -> bool:
    """Return True when the request explicitly asked for optimized streaming.

    Honors (in priority order):
      * ``?optimize_stream=true`` query parameter
      * ``X-Stream-Optimize: 1|true|yes`` request header
      * ``Accept`` containing the token ``stream-optimized``
      * ``X-Stream-Optimize-Auto: 1`` together with a browser User-Agent
    """
    try:
        qp = request.query_params.get("optimize_stream")
        if qp is not None and str(qp).strip().lower() in {"1", "true", "yes", "on"}:
            return True
        for header_name in ("x-stream-optimize",):
            v = request.headers.get(header_name)
            if v is not None and str(v).strip().lower() in {"1", "true", "yes", "on"}:
                return True
        if "stream-optimized" in (request.headers.get("accept") or "").lower():
            return True
        auto = request.headers.get("x-stream-optimize-auto")
        if auto is not None and str(auto).strip().lower() in {"1", "true", "yes", "on"}:
            ua = (request.headers.get("user-agent") or "").lower()
            if ua.startswith("mozilla/"):
                return True
    except Exception:  # noqa: BLE001
        return False
    return False


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


def optimized_sse_frame(event: Any) -> str | None:
    """Render a single StreamEvent (or sentinel) as an SSE frame string.

    Returns ``None`` for the HEARTBEAT_SENTINEL / END_SENTINEL sentinels --
    callers should handle those explicitly.
    """
    if event is HEARTBEAT_SENTINEL or event is END_SENTINEL:
        return None
    return sse_frame(event=event.event, event_id=event.id, data=event.data)


__all__ = [
    "SSE_HEADERS",
    "SSE_MEDIA_TYPE",
    "build_stream_proxy",
    "optimized_sse_frame",
    "should_optimize_for_request",
    "sse_frame",
    "sse_streaming_response",
]
