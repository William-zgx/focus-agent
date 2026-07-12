import asyncio

from focus_agent.config import Settings
from focus_agent.harness import HarnessConfig, create_focus_agent
from focus_agent.harness.observability import InMemoryRunJournal, JournaledStreamBridge
from focus_agent.harness.streaming import (
    END_SENTINEL,
    AgentEventPublisher,
    InMemoryStreamBridge,
    canonical_event_payload,
)


async def _wait_until(predicate, *, timeout: float = 1.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() >= deadline:
            raise AssertionError("condition was not met before timeout")
        await asyncio.sleep(0.001)


def test_publish_end_retains_events_during_cleanup_delay_then_releases_state():
    async def scenario():
        bridge = InMemoryStreamBridge(max_buffer_size=10, cleanup_delay_seconds=0.02)
        published = await bridge.publish("run-1", "message.delta", {"delta": "hello"})

        await bridge.publish_end("run-1")

        assert await bridge.snapshot("run-1") == [published]
        received = []
        async for event in bridge.subscribe("run-1", heartbeat_interval=0):
            received.append(event)
        assert received == [published, END_SENTINEL]
        assert "run-1" in bridge._streams
        assert "run-1" in bridge._counters

        await _wait_until(lambda: "run-1" not in bridge._streams)
        assert "run-1" not in bridge._counters
        assert bridge._cleanup_tasks == {}

    asyncio.run(scenario())


def test_publish_end_without_prior_events_retains_terminal_window():
    async def scenario():
        bridge = InMemoryStreamBridge(max_buffer_size=10, cleanup_delay_seconds=0.02)

        await bridge.publish_end("run-empty")

        assert await bridge.stream_ended("run-empty") is True
        received = [event async for event in bridge.subscribe("run-empty", heartbeat_interval=0)]
        assert received == [END_SENTINEL]
        await _wait_until(lambda: "run-empty" not in bridge._streams)
        assert bridge._counters == {}
        assert bridge._cleanup_tasks == {}

    asyncio.run(scenario())


def test_run_closed_schedules_cleanup_while_journal_replay_remains_available():
    async def scenario():
        journal = InMemoryRunJournal()
        await journal.put("run-1", thread_id="thread-1", status="running")
        memory_bridge = InMemoryStreamBridge(max_buffer_size=10, cleanup_delay_seconds=0)
        bridge = JournaledStreamBridge(journal=journal, bridge=memory_bridge)

        closed = await bridge.publish(
            "run-1",
            "run.closed",
            canonical_event_payload(
                run_id="run-1",
                thread_id="thread-1",
                turn_id="run-1",
                sequence=1,
                status="closed",
            ),
        )
        await _wait_until(lambda: "run-1" not in memory_bridge._streams)

        replayed = []
        async for event in bridge.subscribe("run-1", heartbeat_interval=0):
            replayed.append(event)

        assert replayed == [closed, END_SENTINEL]
        assert memory_bridge._counters == {}
        assert memory_bridge._cleanup_tasks == {}

    asyncio.run(scenario())


def test_many_completed_runs_release_streams_counters_and_cleanup_tasks():
    async def scenario():
        bridge = InMemoryStreamBridge(max_buffer_size=2, cleanup_delay_seconds=0)
        run_ids = [f"run-{index}" for index in range(250)]

        await asyncio.gather(
            *(bridge.publish(run_id, "run.completed", {"run_id": run_id}) for run_id in run_ids)
        )
        await asyncio.gather(*(bridge.publish_end(run_id) for run_id in run_ids))
        await _wait_until(lambda: not bridge._streams)

        assert bridge._counters == {}
        assert bridge._cleanup_tasks == {}

    asyncio.run(scenario())


def test_duplicate_end_cleanup_and_shutdown_are_idempotent_without_task_leaks():
    async def scenario():
        bridge = InMemoryStreamBridge(max_buffer_size=10, cleanup_delay_seconds=60)
        await bridge.publish("run-1", "message.delta", {"delta": "hello"})

        await asyncio.gather(*(bridge.publish_end("run-1") for _ in range(20)))
        cleanup_tasks = list(bridge._cleanup_tasks.values())
        assert len(cleanup_tasks) == 1

        await asyncio.gather(bridge.cleanup("run-1"), bridge.cleanup("run-1"))
        assert "run-1" not in bridge._streams
        assert "run-1" not in bridge._counters
        assert bridge._cleanup_tasks == {}
        assert all(task.done() for task in cleanup_tasks)

        await asyncio.gather(bridge.close(), bridge.close(), bridge.shutdown())
        assert bridge._streams == {}
        assert bridge._counters == {}
        assert bridge._cleanup_tasks == {}

    asyncio.run(scenario())


def test_stale_delayed_cleanup_does_not_cancel_reused_run_cleanup():
    async def scenario():
        bridge = InMemoryStreamBridge(max_buffer_size=10, cleanup_delay_seconds=60)
        await bridge.publish("run-1", "message.delta", {"delta": "first"})
        await bridge.publish_end("run-1")
        stale_cleanup = asyncio.create_task(bridge.cleanup("run-1", delay=0.02))
        await asyncio.sleep(0)
        await bridge.cleanup("run-1")

        await bridge.publish("run-1", "message.delta", {"delta": "second"})
        await bridge.publish_end("run-1")
        replacement_task = bridge._cleanup_tasks["run-1"]

        await stale_cleanup
        assert bridge._cleanup_tasks["run-1"] is replacement_task
        assert not replacement_task.cancelled()
        await bridge.cleanup("run-1")
        assert bridge._cleanup_tasks == {}

    asyncio.run(scenario())


def test_factory_wires_configured_cleanup_delay(monkeypatch):
    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.build_graph",
        lambda **kwargs: object(),
    )

    harness = create_focus_agent(
        HarnessConfig(streaming={"cleanup_delay_seconds": 1.25}),
        settings=Settings(),
    )

    assert harness.stream_bridge.bridge._cleanup_delay_seconds == 1.25


def test_publisher_concurrent_close_emits_single_closed_event_and_end():
    class RecordingBridge:
        def __init__(self):
            self.events = []
            self.end_calls = 0

        async def publish(self, run_id, event, data):
            await asyncio.sleep(0)
            self.events.append((run_id, event, data))

        async def publish_end(self, run_id):
            await asyncio.sleep(0)
            self.end_calls += 1

    async def scenario():
        bridge = RecordingBridge()
        publisher = AgentEventPublisher(
            bridge=bridge,
            run_id="run-1",
            thread_id="thread-1",
        )

        await asyncio.gather(*(publisher.close() for _ in range(20)))

        assert [event for _, event, _ in bridge.events] == ["run.closed"]
        assert bridge.end_calls == 1

    asyncio.run(scenario())
