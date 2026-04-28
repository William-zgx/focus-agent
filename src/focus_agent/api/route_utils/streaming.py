from __future__ import annotations

from typing import AsyncIterator

from fastapi.responses import StreamingResponse


def _event_stream_response(stream: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(
        stream,
        media_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
        },
    )




__all__ = [
    "_event_stream_response",
]
