from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable

logger = logging.getLogger("focus_agent.lifecycle")

_shutdown_hooks: list[Callable[[], Awaitable[None]]] = []
_shutdown_event: asyncio.Event | None = None


def shutdown_event() -> asyncio.Event:
    global _shutdown_event
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if _shutdown_event is None or (loop is not None and _shutdown_event._loop not in (None, loop)):
        _shutdown_event = asyncio.Event()
    return _shutdown_event


def is_shutting_down() -> bool:
    return _shutdown_event is not None and _shutdown_event.is_set()


def register_shutdown_hook(fn: Callable[[], Awaitable[None]]) -> None:
    if fn not in _shutdown_hooks:
        _shutdown_hooks.append(fn)


def unregister_shutdown_hook(fn: Callable[[], Awaitable[None]]) -> None:
    try:
        _shutdown_hooks.remove(fn)
    except ValueError:
        return


def reset_shutdown_state() -> None:
    global _shutdown_event
    _shutdown_event = None


async def trigger_shutdown(timeout: float = 30.0) -> None:
    shutdown_event().set()

    async def _run_hooks() -> None:
        for hook in reversed(_shutdown_hooks):
            try:
                await asyncio.wait_for(hook(), timeout=5.0)
            except Exception:  # noqa: BLE001
                logger.warning("shutdown hook failed", exc_info=True)

    await asyncio.wait_for(_run_hooks(), timeout=timeout)


def install_signal_handlers(loop: asyncio.AbstractEventLoop | None = None) -> None:
    target_loop = loop or asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            target_loop.add_signal_handler(
                sig,
                lambda sig=sig: asyncio.create_task(trigger_shutdown()),
            )
        except (NotImplementedError, RuntimeError):
            logger.debug("signal handlers unavailable for %s", sig)


__all__ = [
    "install_signal_handlers",
    "is_shutting_down",
    "register_shutdown_hook",
    "reset_shutdown_state",
    "shutdown_event",
    "trigger_shutdown",
    "unregister_shutdown_hook",
]
