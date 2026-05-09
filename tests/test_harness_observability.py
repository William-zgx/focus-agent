import asyncio

from focus_agent.harness.observability import (
    InMemoryRunJournal,
    JournaledStreamBridge,
    SQLiteRunJournal,
)
from focus_agent.harness.runtime import RunManager, RunStatus
from focus_agent.harness.streaming import (
    END_SENTINEL,
    HEARTBEAT_SENTINEL,
    InMemoryStreamBridge,
    canonical_event_payload,
)


def test_in_memory_run_journal_records_runs_events_and_tool_events():
    async def scenario():
        journal = InMemoryRunJournal()
        manager = RunManager(store=journal)
        run = await manager.create(
            "thread-1",
            "focus-agent",
            metadata={"suite": "harness"},
        )
        await manager.set_status(run.run_id, RunStatus.RUNNING)

        requested = await journal.append_event(
            run.run_id,
            "tool.requested",
            canonical_event_payload(
                run_id=run.run_id,
                thread_id="thread-1",
                turn_id="turn-1",
                sequence=1,
                tool_call_id="call-1",
                tool_name="search_code",
                args={"query": "StreamBridge"},
            ),
        )
        await journal.append_event(
            run.run_id,
            "tool.result",
            {
                "tool_call_id": "call-1",
                "tool_name": "search_code",
                "args": {"query": "StreamBridge"},
                "result": "found bridge.py",
                "duration_ms": 12.5,
            },
        )

        assert requested.sequence == 1
        assert await journal.count_events(run.run_id) == 2
        assert await journal.count_tool_events(run.run_id, tool_name="search_code") == 2

        snapshot = await journal.snapshot(run.run_id)
        assert snapshot["run"]["metadata"] == {"suite": "harness"}
        assert snapshot["run"]["status"] == "running"
        assert snapshot["counts"] == {"events": 2, "tool_events": 2}
        assert snapshot["tool_events"][0]["status"] == "requested"

        trajectory = await journal.trajectory_summary(run.run_id)
        assert trajectory["id"] == run.run_id
        assert trajectory["kind"] == "harness_run"
        assert trajectory["metrics"]["tool_calls"] == 1
        assert trajectory["trajectory"][0]["tool"] == "search_code"
        assert trajectory["trajectory"][0]["observation"] == "found bridge.py"

    asyncio.run(scenario())


def test_journaled_stream_bridge_persists_published_canonical_events():
    async def scenario():
        journal = InMemoryRunJournal()
        await journal.put("run-1", thread_id="thread-1", status="running")
        bridge = JournaledStreamBridge(
            journal=journal,
            bridge=InMemoryStreamBridge(max_buffer_size=10),
        )

        stream_event = await bridge.publish(
            "run-1",
            "message.delta",
            canonical_event_payload(
                run_id="run-1",
                thread_id="thread-1",
                turn_id="turn-1",
                sequence=3,
                delta="hello",
            ),
        )

        snapshot = await journal.snapshot("run-1")
        assert snapshot["events"][0]["stream_event_id"] == stream_event.id
        assert snapshot["events"][0]["event"] == "message.delta"
        assert snapshot["events"][0]["data"]["delta"] == "hello"

        replay = await bridge.snapshot("run-1")
        assert replay[0] == stream_event

    asyncio.run(scenario())


def test_journaled_stream_bridge_replays_after_last_event_id_from_journal():
    async def scenario():
        journal = InMemoryRunJournal()
        await journal.put("run-1", thread_id="thread-1", status="running")
        bridge = JournaledStreamBridge(
            journal=journal,
            bridge=InMemoryStreamBridge(max_buffer_size=1),
        )

        first = await bridge.publish(
            "run-1",
            "message.delta",
            canonical_event_payload(
                run_id="run-1",
                thread_id="thread-1",
                turn_id="turn-1",
                sequence=1,
                delta="first",
            ),
        )
        second = await bridge.publish(
            "run-1",
            "message.delta",
            canonical_event_payload(
                run_id="run-1",
                thread_id="thread-1",
                turn_id="turn-1",
                sequence=2,
                delta="second",
            ),
        )
        closed = await bridge.publish(
            "run-1",
            "run.closed",
            canonical_event_payload(
                run_id="run-1",
                thread_id="thread-1",
                turn_id="turn-1",
                sequence=3,
                status="closed",
            ),
        )

        replayed = []
        async for event in bridge.subscribe("run-1", last_event_id=first.id, heartbeat_interval=None):
            if event is END_SENTINEL:
                break
            replayed.append(event)

        assert [event.id for event in replayed] == [second.id, closed.id]
        assert [event.data["sequence"] for event in replayed] == [2, 3]

    asyncio.run(scenario())


def test_journaled_stream_bridge_closes_replay_for_terminal_run_without_closed_event():
    async def scenario():
        journal = InMemoryRunJournal()
        await journal.put("run-1", thread_id="thread-1", status="running")
        bridge = JournaledStreamBridge(
            journal=journal,
            bridge=InMemoryStreamBridge(max_buffer_size=1),
        )
        first = await bridge.publish(
            "run-1",
            "run.completed",
            canonical_event_payload(
                run_id="run-1",
                thread_id="thread-1",
                turn_id="turn-1",
                sequence=1,
                status="succeeded",
            ),
        )
        await journal.update_status("run-1", "success")
        await bridge.publish_end("run-1")

        replayed = []
        async for event in bridge.subscribe("run-1", last_event_id=None, heartbeat_interval=0):
            replayed.append(event)
            if event is END_SENTINEL:
                break

        assert replayed == [first, END_SENTINEL]

    asyncio.run(scenario())


def test_journaled_stream_bridge_does_not_end_active_terminal_run_before_closed_event():
    async def scenario():
        journal = InMemoryRunJournal()
        await journal.put("run-1", thread_id="thread-1", status="running")
        bridge = JournaledStreamBridge(
            journal=journal,
            bridge=InMemoryStreamBridge(max_buffer_size=10),
        )
        first = await bridge.publish(
            "run-1",
            "run.interrupt",
            canonical_event_payload(
                run_id="run-1",
                thread_id="thread-1",
                turn_id="turn-1",
                sequence=1,
                action="rollback",
            ),
        )
        await journal.update_status("run-1", "interrupted")

        subscription = bridge.subscribe("run-1", last_event_id=None, heartbeat_interval=0)
        try:
            assert await anext(subscription) == first
            assert await asyncio.wait_for(anext(subscription), timeout=1) is HEARTBEAT_SENTINEL
        finally:
            await subscription.aclose()

    asyncio.run(scenario())


def test_sqlite_run_journal_persists_snapshot_and_trajectory(tmp_path):
    async def scenario():
        db_path = tmp_path / "harness-runs.sqlite3"
        journal = SQLiteRunJournal(db_path)
        await journal.put(
            "run-1",
            thread_id="thread-1",
            assistant_id="focus-agent",
            on_disconnect="rollback",
            metadata={"origin": "test"},
        )
        await journal.update_status("run-1", "success")
        await journal.update_run_completion("run-1", prompt_tokens=7, completion_tokens=11)
        await journal.append_event("run-1", "run.metadata", {"thread_id": "thread-1"})
        await journal.append_event(
            "run-1",
            "tool.error",
            {
                "tool_call_id": "call-err",
                "tool_name": "write_artifact",
                "args": {"path": "/tmp/out"},
                "error": "denied",
            },
        )

        reopened = SQLiteRunJournal(db_path)
        snapshot = await reopened.snapshot("run-1")
        assert snapshot["run"]["status"] == "success"
        assert snapshot["run"]["on_disconnect"] == "rollback"
        assert snapshot["run"]["completion"] == {
            "completion_tokens": 11,
            "prompt_tokens": 7,
        }
        assert snapshot["counts"] == {"events": 2, "tool_events": 1}
        assert snapshot["tool_events"][0]["status"] == "error"

        trajectory = await reopened.trajectory_summary("run-1")
        assert trajectory["status"] == "success"
        assert trajectory["trajectory"][0]["tool"] == "write_artifact"
        assert trajectory["trajectory"][0]["error"] == "denied"

    asyncio.run(scenario())
