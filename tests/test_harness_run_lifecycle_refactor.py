import asyncio
import inspect
from pathlib import Path

from focus_agent.harness import runtime
from focus_agent.harness.runtime import runs


def test_run_lifecycle_public_api_remains_owned_by_runs_module():
    assert runtime.RunStatus is runs.RunStatus
    assert runtime.RunRequest is runs.RunRequest
    assert runtime.RunRecord is runs.RunRecord
    assert runtime.RunManager is runs.RunManager
    assert runs.RunManager.__module__ == runs.__name__

    signature = inspect.signature(runs.RunManager)
    assert list(signature.parameters) == [
        "store",
        "rollback_handler",
        "lifecycle_publisher",
        "enable_followup_drain",
    ]


def test_run_manager_followup_mixin_preserves_fifo_queue_behavior():
    async def scenario():
        manager = runs.RunManager()

        await manager.steer("thread-1", "steer-1")
        await manager.steer("thread-1", "steer-2")
        await manager.follow_up("thread-1", "followup-1")
        await manager.follow_up("thread-1", "followup-2")

        assert manager.queue_depth("thread-1") == {"steer": 2, "followup": 2}
        assert await manager.drain_steer_queue("thread-1") == ["steer-1", "steer-2"]
        assert manager.drain_followup_queue_nowait("thread-1") == [
            "followup-1",
            "followup-2",
        ]
        assert manager.queue_depth("thread-1") == {"steer": 0, "followup": 0}

    asyncio.run(scenario())


def test_run_manager_followup_worker_starts_once_and_dispatches_messages():
    async def scenario():
        manager = runs.RunManager(enable_followup_drain=True)
        dispatched = []
        dispatch_complete = asyncio.Event()

        async def handler(thread_id, message):
            dispatched.append((thread_id, message))
            if len(dispatched) == 2:
                dispatch_complete.set()

        manager.set_followup_handler(handler)
        assert manager.start_followup_drain() is True
        assert manager.start_followup_drain() is False

        try:
            await manager.follow_up("thread-1", "first")
            await manager.follow_up("thread-1", "second")
            await asyncio.wait_for(dispatch_complete.wait(), timeout=1)
        finally:
            await manager.stop_followup_drain()

        assert dispatched == [("thread-1", "first"), ("thread-1", "second")]
        assert manager.queue_depth("thread-1")["followup"] == 0

    asyncio.run(scenario())


def test_runs_module_stays_within_line_budget():
    runs_path = Path(runs.__file__)
    assert len(runs_path.read_text(encoding="utf-8").splitlines()) <= 800
