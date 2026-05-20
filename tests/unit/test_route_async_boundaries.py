from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

from focus_agent.api.route_helpers import run_sync_route_call
from focus_agent.api.route_utils.branch_handoff_decisions import (
    ensure_branch_handoff_decision_from_journal,
)


def _wait_for_release(
    started: threading.Event,
    release: threading.Event,
    value: str,
) -> str:
    started.set()
    if not release.wait(timeout=2):
        raise TimeoutError("sync route call was not released")
    return value


async def _wait_until_started(started: threading.Event) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 1
    while not started.is_set():
        if loop.time() >= deadline:
            raise AssertionError("sync route call did not start")
        await asyncio.sleep(0.001)


def test_run_sync_route_call_does_not_block_event_loop() -> None:
    async def scenario() -> None:
        started = threading.Event()
        release = threading.Event()
        blocking = asyncio.create_task(
            run_sync_route_call(_wait_for_release, started, release, "done")
        )

        await _wait_until_started(started)
        assert await asyncio.sleep(0.01, result="tick") == "tick"
        assert not blocking.done()

        release.set()
        assert await blocking == "done"

    asyncio.run(scenario())


def test_branch_handoff_journal_helper_does_not_block_event_loop() -> None:
    class Service:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.release = threading.Event()

        def list_decisions(self, **_kwargs):
            self.started.set()
            if not self.release.wait(timeout=2):
                raise TimeoutError("branch decision service was not released")
            return [SimpleNamespace(decision_id="decision-1")]

    async def scenario() -> None:
        service = Service()
        runtime = SimpleNamespace(branch_decision_service=service)
        blocking = asyncio.create_task(
            ensure_branch_handoff_decision_from_journal(
                runtime=runtime,
                thread_id="thread-1",
                user_id="user-1",
            )
        )

        await _wait_until_started(service.started)
        assert await asyncio.sleep(0.01, result="tick") == "tick"
        assert not blocking.done()

        service.release.set()
        assert (await blocking).decision_id == "decision-1"

    asyncio.run(scenario())
