import asyncio
import threading

import pytest

from focus_agent.core import async_threads
from focus_agent.services.chat import turns


def test_call_in_daemon_thread_marks_worker_daemon(monkeypatch):
    real_thread = threading.Thread
    created_threads: list[threading.Thread] = []

    def capture_thread(*args, **kwargs):
        thread = real_thread(*args, **kwargs)
        created_threads.append(thread)
        return thread

    monkeypatch.setattr(async_threads.threading, "Thread", capture_thread)

    async def scenario():
        assert await turns._call_in_daemon_thread(lambda: "ok") == "ok"

    asyncio.run(scenario())

    assert created_threads
    assert created_threads[0].daemon is True


def test_close_stream_iter_does_not_hang_on_slow_async_close(monkeypatch):
    monkeypatch.setattr(turns, "_STREAM_SHUTDOWN_TIMEOUT_SECONDS", 0.01)

    class SlowAsyncClose:
        def __init__(self):
            self.close_started = asyncio.Event()

        async def aclose(self):
            self.close_started.set()
            await asyncio.sleep(60)

    async def scenario():
        stream = SlowAsyncClose()
        await asyncio.wait_for(
            turns._close_stream_iter(stream_iter=stream, close_method="aclose"),
            timeout=0.5,
        )
        assert stream.close_started.is_set()

    asyncio.run(scenario())


def test_consume_graph_stream_cancel_has_bounded_shutdown(monkeypatch):
    monkeypatch.setattr(turns, "_STREAM_SHUTDOWN_TIMEOUT_SECONDS", 0.01)

    class SlowGraphStream:
        def __init__(self):
            self.next_started = asyncio.Event()
            self.close_started = asyncio.Event()

        async def __anext__(self):
            self.next_started.set()
            await asyncio.sleep(60)

        async def aclose(self):
            self.close_started.set()
            await asyncio.sleep(60)

    async def scenario():
        stream = SlowGraphStream()

        async def collect():
            async for _chunk in turns._consume_graph_stream(
                stream_iter=stream,
                heartbeat_interval=0,
                next_chunk=lambda: turns._next_graph_chunk(stream),
                close_method="aclose",
            ):
                pass

        task = asyncio.create_task(collect())
        await asyncio.wait_for(stream.next_started.wait(), timeout=0.5)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=0.5)
        assert stream.close_started.is_set()

    asyncio.run(scenario())


def test_consume_graph_stream_sync_cancel_has_bounded_shutdown(monkeypatch):
    monkeypatch.setattr(turns, "_STREAM_SHUTDOWN_TIMEOUT_SECONDS", 0.01)

    class StubbornSyncStream:
        def __init__(self):
            self.next_started = threading.Event()
            self.release_next = threading.Event()
            self.close_started = False

        def __next__(self):
            self.next_started.set()
            self.release_next.wait()
            return turns._STREAM_END

        def close(self):
            self.close_started = True

    async def scenario():
        stream = StubbornSyncStream()

        async def collect():
            async for _chunk in turns._consume_graph_stream(
                stream_iter=stream,
                heartbeat_interval=0,
                next_chunk=lambda: turns._call_in_daemon_thread(next, stream, turns._STREAM_END),
                close_method="close",
            ):
                pass

        task = asyncio.create_task(collect())
        while not stream.next_started.is_set():
            await asyncio.sleep(0.005)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=0.5)
        assert stream.close_started is False

        stream.release_next.set()
        await asyncio.sleep(0.05)

    asyncio.run(scenario())


def test_consume_graph_stream_skips_close_when_next_chunk_will_not_cancel(monkeypatch):
    monkeypatch.setattr(turns, "_STREAM_SHUTDOWN_TIMEOUT_SECONDS", 0.01)

    class StubbornGraphStream:
        def __init__(self):
            self.next_started = asyncio.Event()
            self.release_next = asyncio.Event()
            self.close_started = False

        async def __anext__(self):
            self.next_started.set()
            try:
                await self.release_next.wait()
            except asyncio.CancelledError:
                await self.release_next.wait()
            raise StopAsyncIteration

        async def aclose(self):
            self.close_started = True

    async def scenario():
        stream = StubbornGraphStream()

        async def collect():
            async for _chunk in turns._consume_graph_stream(
                stream_iter=stream,
                heartbeat_interval=0,
                next_chunk=lambda: turns._next_graph_chunk(stream),
                close_method="aclose",
            ):
                pass

        task = asyncio.create_task(collect())
        await asyncio.wait_for(stream.next_started.wait(), timeout=0.5)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=0.5)
        assert stream.close_started is False

        stream.release_next.set()
        await asyncio.sleep(0)

    asyncio.run(scenario())
