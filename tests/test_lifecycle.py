from __future__ import annotations

import asyncio

from focus_agent.runtime.lifecycle import (
    is_shutting_down,
    register_shutdown_hook,
    reset_shutdown_state,
    trigger_shutdown,
    unregister_shutdown_hook,
)


def test_trigger_shutdown_sets_flag_and_runs_registered_hooks() -> None:
    reset_shutdown_state()
    calls: list[str] = []

    async def hook() -> None:
        calls.append("hook")

    register_shutdown_hook(hook)
    try:
        asyncio.run(trigger_shutdown())
    finally:
        unregister_shutdown_hook(hook)

    assert is_shutting_down() is True
    assert calls == ["hook"]


def test_reset_shutdown_state_clears_drain_flag_between_app_lifespans() -> None:
    reset_shutdown_state()
    assert is_shutting_down() is False
