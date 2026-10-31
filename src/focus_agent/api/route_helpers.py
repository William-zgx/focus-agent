"""Shared helpers for API route handlers."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


async def run_sync_route_call(func: Callable[P, R], /, *args: P.args, **kwargs: P.kwargs) -> R:
    """Run blocking service/repository code off the event loop from an async route."""
    return await asyncio.to_thread(func, *args, **kwargs)


__all__ = ["run_sync_route_call"]
