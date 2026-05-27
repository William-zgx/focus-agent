from __future__ import annotations

import asyncio
import threading
from contextlib import suppress
from typing import Any


async def call_in_daemon_thread(
    func: Any,
    *args: Any,
    wait_on_cancel: bool = True,
    **kwargs: Any,
) -> Any:
    loop = asyncio.get_running_loop()
    future: asyncio.Future[Any] = loop.create_future()

    def complete(method: str, *values: Any) -> None:
        if future.done():
            return
        getattr(future, method)(*values)

    def complete_threadsafe(method: str, *values: Any) -> None:
        with suppress(RuntimeError):
            loop.call_soon_threadsafe(complete, method, *values)

    def run() -> None:
        try:
            result = func(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001
            complete_threadsafe("set_exception", exc)
            return
        complete_threadsafe("set_result", result)

    threading.Thread(target=run, name="focus-agent-worker", daemon=True).start()
    try:
        return await asyncio.shield(future)
    except asyncio.CancelledError:
        if wait_on_cancel and not future.done():
            with suppress(asyncio.CancelledError):
                await asyncio.shield(future)
        raise
