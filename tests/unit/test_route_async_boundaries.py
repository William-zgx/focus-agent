from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

from focus_agent.api.route_helpers import run_sync_route_call
from focus_agent.api.route_utils.branch_handoff_decisions import (
    ensure_branch_handoff_decision_from_journal,
)


def _sleep_and_return(delay: float, value: str) -> str:
    time.sleep(delay)
    return value


def test_run_sync_route_call_does_not_block_event_loop() -> None:
    async def scenario() -> None:
        blocking = asyncio.create_task(run_sync_route_call(_sleep_and_return, 0.05, "done"))
        ticker = asyncio.create_task(asyncio.sleep(0.01, result="tick"))

        done, _pending = await asyncio.wait(
            {blocking, ticker},
            timeout=0.2,
            return_when=asyncio.FIRST_COMPLETED,
        )

        assert ticker in done
        assert await ticker == "tick"
        assert await blocking == "done"

    asyncio.run(scenario())


def test_branch_handoff_journal_helper_does_not_block_event_loop() -> None:
    class Service:
        def list_decisions(self, **_kwargs):
            time.sleep(0.05)
            return [SimpleNamespace(decision_id="decision-1")]

    async def scenario() -> None:
        runtime = SimpleNamespace(branch_decision_service=Service())
        blocking = asyncio.create_task(
            ensure_branch_handoff_decision_from_journal(
                runtime=runtime,
                thread_id="thread-1",
                user_id="user-1",
            )
        )
        ticker = asyncio.create_task(asyncio.sleep(0.01, result="tick"))

        done, _pending = await asyncio.wait(
            {blocking, ticker},
            timeout=0.2,
            return_when=asyncio.FIRST_COMPLETED,
        )

        assert ticker in done
        assert await ticker == "tick"
        assert (await blocking).decision_id == "decision-1"

    asyncio.run(scenario())
