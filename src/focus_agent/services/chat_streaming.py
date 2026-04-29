from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any, AsyncIterator

from langgraph.checkpoint.base import BaseCheckpointSaver

_STREAM_END = object()


async def stream_graph_chunks(
    *,
    graph: Any,
    checkpointer: Any,
    settings: Any,
    payload: Any,
    config: dict[str, Any],
    context: Any,
) -> AsyncIterator[dict[str, Any] | None]:
    if checkpointer_lacks_async_support(checkpointer):
        async for chunk in stream_graph_chunks_via_sync_stream(
            graph=graph,
            settings=settings,
            payload=payload,
            config=config,
            context=context,
        ):
            yield chunk
        return

    stream = graph.astream(
        payload,
        config=config,
        context=context,
        stream_mode=['messages', 'custom', 'updates', 'tasks'],
        version='v2',
    )
    stream_iter = stream.__aiter__()
    heartbeat_interval = max(float(settings.sse_heartbeat_seconds), 0.0)
    pending_next: asyncio.Task[Any] | None = None

    try:
        pending_next = asyncio.create_task(anext(stream_iter))
        while pending_next is not None:
            if heartbeat_interval > 0:
                done, _ = await asyncio.wait({pending_next}, timeout=heartbeat_interval)
                if not done:
                    yield None
                    continue
            try:
                chunk = await pending_next
            except StopAsyncIteration:
                pending_next = None
                break
            pending_next = asyncio.create_task(anext(stream_iter))
            yield chunk
    finally:
        if pending_next is not None and not pending_next.done():
            pending_next.cancel()
            with suppress(asyncio.CancelledError):
                await pending_next
        aclose = getattr(stream_iter, 'aclose', None)
        if callable(aclose):
            with suppress(Exception):  # noqa: BLE001
                await aclose()


def checkpointer_lacks_async_support(checkpointer: Any) -> bool:
    if checkpointer is None:
        return False
    return type(checkpointer).aget_tuple is BaseCheckpointSaver.aget_tuple


async def stream_graph_chunks_via_sync_stream(
    *,
    graph: Any,
    settings: Any,
    payload: Any,
    config: dict[str, Any],
    context: Any,
) -> AsyncIterator[dict[str, Any] | None]:
    stream = graph.stream(
        payload,
        config=config,
        context=context,
        stream_mode=['messages', 'custom', 'updates', 'tasks'],
        version='v2',
    )
    stream_iter = iter(stream)
    heartbeat_interval = max(float(settings.sse_heartbeat_seconds), 0.0)
    pending_next: asyncio.Task[Any] | None = None

    try:
        pending_next = asyncio.create_task(asyncio.to_thread(next, stream_iter, _STREAM_END))
        while pending_next is not None:
            if heartbeat_interval > 0:
                done, _ = await asyncio.wait({pending_next}, timeout=heartbeat_interval)
                if not done:
                    yield None
                    continue
            chunk = await pending_next
            if chunk is _STREAM_END:
                pending_next = None
                break
            pending_next = asyncio.create_task(asyncio.to_thread(next, stream_iter, _STREAM_END))
            yield chunk
    finally:
        if pending_next is not None and not pending_next.done():
            pending_next.cancel()
            with suppress(asyncio.CancelledError):
                await pending_next
        close = getattr(stream_iter, 'close', None)
        if callable(close):
            with suppress(Exception):  # noqa: BLE001
                close()
