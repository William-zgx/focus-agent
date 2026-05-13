from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any, AsyncIterator

from langgraph.checkpoint.base import BaseCheckpointSaver

from ..core.repo_call import has_repo_method

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

    stream_iter = graph.astream(
        payload,
        config=config,
        context=context,
        stream_mode=['messages', 'custom', 'updates', 'tasks'],
        version='v2',
    ).__aiter__()

    async for chunk in _consume_graph_stream(
        stream_iter=stream_iter,
        heartbeat_interval=max(float(settings.sse_heartbeat_seconds), 0.0),
        next_chunk=lambda: _next_graph_chunk(stream_iter),
        close_method='aclose',
    ):
        yield chunk


async def stream_graph_chunks_via_sync_stream(
    *,
    graph: Any,
    settings: Any,
    payload: Any,
    config: dict[str, Any],
    context: Any,
) -> AsyncIterator[dict[str, Any] | None]:
    stream_iter = graph.stream(
        payload,
        config=config,
        context=context,
        stream_mode=['messages', 'custom', 'updates', 'tasks'],
        version='v2',
    )
    async for chunk in _consume_graph_stream(
        stream_iter=stream_iter,
        heartbeat_interval=max(float(settings.sse_heartbeat_seconds), 0.0),
        next_chunk=lambda: asyncio.to_thread(next, stream_iter, _STREAM_END),
        close_method='close',
    ):
        yield chunk


async def _consume_graph_stream(
    *,
    stream_iter: Any,
    heartbeat_interval: float,
    next_chunk: Any,
    close_method: str,
) -> AsyncIterator[dict[str, Any] | None]:
    task: asyncio.Task[Any] | None = None
    try:
        task = asyncio.create_task(next_chunk())
        while task is not None:
            if heartbeat_interval > 0:
                done, _ = await asyncio.wait({task}, timeout=heartbeat_interval)
                if not done:
                    yield None
                    continue
            chunk = await task
            if chunk is _STREAM_END:
                break
            task = asyncio.create_task(next_chunk())
            yield chunk
    finally:
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await _close_stream_iter(stream_iter=stream_iter, close_method=close_method)


async def _next_graph_chunk(stream_iter: Any) -> Any:
    try:
        return await anext(stream_iter)
    except StopAsyncIteration:
        return _STREAM_END


async def _close_stream_iter(*, stream_iter: Any, close_method: str) -> None:
    if not has_repo_method(stream_iter, close_method):
        return
    with suppress(Exception):  # noqa: BLE001
        result = getattr(stream_iter, close_method)()
        if close_method == 'aclose' and hasattr(result, '__await__'):
            await result


def checkpointer_lacks_async_support(checkpointer: Any) -> bool:
    if checkpointer is None:
        return False
    return type(checkpointer).aget_tuple is BaseCheckpointSaver.aget_tuple
