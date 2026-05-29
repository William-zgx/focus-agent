from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver

from ...core.async_threads import call_in_daemon_thread as _call_in_daemon_thread
from ...core.repo_call import has_repo_method

logger = logging.getLogger("focus_agent.chat")

_STREAM_END = object()
_STREAM_SHUTDOWN_TIMEOUT_SECONDS = 2.0
_DEFAULT_STREAM_SHUTDOWN_TIMEOUT_SECONDS = _STREAM_SHUTDOWN_TIMEOUT_SECONDS
_TURNS_FACADE_MODULE = "focus_agent.services.chat.turns"


def _stream_shutdown_timeout_seconds() -> float:
    facade = sys.modules.get(_TURNS_FACADE_MODULE)
    if facade is not None:
        facade_timeout = getattr(facade, "_STREAM_SHUTDOWN_TIMEOUT_SECONDS", None)
        if (
            facade_timeout is not None
            and facade_timeout != _DEFAULT_STREAM_SHUTDOWN_TIMEOUT_SECONDS
        ):
            return float(facade_timeout)
    return float(_STREAM_SHUTDOWN_TIMEOUT_SECONDS)


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
        stream_mode=["messages", "custom", "updates", "tasks"],
        version="v2",
    ).__aiter__()

    async for chunk in _consume_graph_stream(
        stream_iter=stream_iter,
        heartbeat_interval=max(float(settings.sse_heartbeat_seconds), 0.0),
        next_chunk=lambda: _next_graph_chunk(stream_iter),
        close_method="aclose",
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
        stream_mode=["messages", "custom", "updates", "tasks"],
        version="v2",
    )
    async for chunk in _consume_graph_stream(
        stream_iter=stream_iter,
        heartbeat_interval=max(float(settings.sse_heartbeat_seconds), 0.0),
        next_chunk=lambda: _call_in_daemon_thread(next, stream_iter, _STREAM_END),
        close_method="close",
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
            chunk = await asyncio.shield(task)
            if chunk is _STREAM_END:
                break
            task = asyncio.create_task(next_chunk())
            yield chunk
    finally:
        next_task_settled = True
        if task is not None and not task.done():
            next_task_settled = await _cancel_task_with_timeout(
                task,
                label="graph stream next chunk",
            )
        if next_task_settled:
            await _close_stream_iter(stream_iter=stream_iter, close_method=close_method)
        else:
            logger.warning("Skipping graph stream close because next chunk is still executing")


async def _next_graph_chunk(stream_iter: Any) -> Any:
    try:
        return await anext(stream_iter)
    except StopAsyncIteration:
        return _STREAM_END


async def _close_stream_iter(*, stream_iter: Any, close_method: str) -> None:
    if not has_repo_method(stream_iter, close_method):
        return
    close = getattr(stream_iter, close_method)
    if close_method == "aclose":
        with suppress(Exception):  # noqa: BLE001
            result = close()
            if hasattr(result, "__await__"):
                await _await_with_timeout(
                    result,
                    label="async graph stream close",
                )
        return
    with suppress(Exception):  # noqa: BLE001
        await _await_with_timeout(
            _call_in_daemon_thread(close),
            label="sync graph stream close",
        )


def _consume_task_result(task: asyncio.Task[Any]) -> None:
    with suppress(asyncio.CancelledError, Exception):  # noqa: BLE001
        task.result()


async def _cancel_task_with_timeout(task: asyncio.Task[Any], *, label: str) -> bool:
    timeout = _stream_shutdown_timeout_seconds()
    task.cancel()
    done, _ = await asyncio.wait(
        {task},
        timeout=timeout,
    )
    if task in done:
        _consume_task_result(task)
        return True
    task.add_done_callback(_consume_task_result)
    logger.warning(
        "Timed out waiting for %s cancellation after %.1fs",
        label,
        timeout,
    )
    return False


async def _await_with_timeout(awaitable: Any, *, label: str) -> Any:
    timeout = _stream_shutdown_timeout_seconds()
    task = asyncio.ensure_future(awaitable)
    done, _ = await asyncio.wait(
        {task},
        timeout=timeout,
    )
    if task in done:
        return await task
    task.cancel()
    task.add_done_callback(_consume_task_result)
    logger.warning(
        "Timed out waiting for %s after %.1fs",
        label,
        timeout,
    )
    return None


def checkpointer_lacks_async_support(checkpointer: Any) -> bool:
    if checkpointer is None:
        return False
    return type(checkpointer).aget_tuple is BaseCheckpointSaver.aget_tuple
