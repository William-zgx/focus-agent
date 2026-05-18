from __future__ import annotations

from typing import Any

from fastapi.responses import StreamingResponse

SSE_MEDIA_TYPE = "text/event-stream"
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def sse_streaming_response(content: Any) -> StreamingResponse:
    return StreamingResponse(content, media_type=SSE_MEDIA_TYPE, headers=dict(SSE_HEADERS))
