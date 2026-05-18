from __future__ import annotations

from focus_agent.api.streaming import SSE_HEADERS, SSE_MEDIA_TYPE, sse_streaming_response


def test_sse_streaming_response_sets_sse_headers():
    response = sse_streaming_response(iter(["data: ok\n\n"]))

    assert response.media_type == SSE_MEDIA_TYPE
    assert response.headers["cache-control"] == SSE_HEADERS["Cache-Control"]
    assert response.headers["connection"] == SSE_HEADERS["Connection"]
    assert response.headers["x-accel-buffering"] == SSE_HEADERS["X-Accel-Buffering"]
