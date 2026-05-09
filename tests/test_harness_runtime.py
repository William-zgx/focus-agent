import asyncio
import json

import pytest

from focus_agent.harness.runtime import (
    MultitaskStrategy,
    RunConflictError,
    RunManager,
    RunStatus,
)
from focus_agent.harness.streaming import (
    END_SENTINEL,
    InMemoryStreamBridge,
    canonical_event_payload,
    sse_frame,
)


def test_run_manager_rejects_concurrent_run_on_same_thread():
    async def scenario():
        manager = RunManager()
        first = await manager.create_or_reject("thread-1", "focus-agent")
        await manager.set_status(first.run_id, RunStatus.RUNNING)

        with pytest.raises(RunConflictError):
            await manager.create_or_reject("thread-1", "focus-agent")

    asyncio.run(scenario())


def test_run_manager_interrupt_marks_inflight_run_and_creates_next():
    async def scenario():
        manager = RunManager()
        first = await manager.create_or_reject("thread-1", "focus-agent")
        await manager.set_status(first.run_id, RunStatus.RUNNING)

        second = await manager.create_or_reject(
            "thread-1",
            "focus-agent",
            multitask_strategy=MultitaskStrategy.INTERRUPT,
        )

        assert second.run_id != first.run_id
        assert first.abort_event.is_set()
        assert first.abort_action == "interrupt"
        assert first.status is RunStatus.INTERRUPTED

    asyncio.run(scenario())


def test_stream_bridge_replays_from_last_event_id_and_closes():
    async def scenario():
        bridge = InMemoryStreamBridge(max_buffer_size=10)
        first = await bridge.publish("run-1", "run.metadata", {"sequence": 1})
        second = await bridge.publish("run-1", "message.delta", {"sequence": 2})
        await bridge.publish_end("run-1")

        received = []
        async for event in bridge.subscribe(
            "run-1",
            last_event_id=first.id,
            heartbeat_interval=0,
        ):
            received.append(event)

        assert received[0] == second
        assert received[-1] is END_SENTINEL

    asyncio.run(scenario())


def test_canonical_sse_payload_has_required_run_fields():
    payload = canonical_event_payload(
        run_id="run-1",
        thread_id="thread-1",
        turn_id="turn-1",
        sequence=7,
        source_node="agent",
        delta="hello",
        message_id="msg-1",
    )

    assert payload == {
        "run_id": "run-1",
        "thread_id": "thread-1",
        "turn_id": "turn-1",
        "sequence": 7,
        "source_node": "agent",
        "delta": "hello",
        "message_id": "msg-1",
    }
    frame = sse_frame(event="message.delta", event_id="evt-1", data=payload)
    assert frame.startswith("id: evt-1\nevent: message.delta\n")
    assert json.loads(frame.split("data: ", 1)[1])["run_id"] == "run-1"
