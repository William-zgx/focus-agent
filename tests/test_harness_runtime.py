import asyncio
import json
import operator
from typing import Annotated

from langgraph.graph import END, START, StateGraph
import pytest
from typing_extensions import TypedDict

from focus_agent.engine.local_persistence import PersistentInMemorySaver
from focus_agent.harness.runtime import (
    MultitaskStrategy,
    RunConflictError,
    RunManager,
    RunStatus,
)
from focus_agent.harness.runtime.rollback import (
    CheckpointRollbackTarget,
    capture_checkpoint_rollback_target,
    restore_graph_rollback_target,
)
from focus_agent.harness.streaming import (
    END_SENTINEL,
    InMemoryStreamBridge,
    canonical_event_payload,
    sse_frame,
)


class _RollbackGraphState(TypedDict):
    messages: Annotated[list[str], operator.add]


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


def test_run_manager_interrupt_waits_for_cancelled_task_cleanup():
    async def scenario():
        manager = RunManager()
        first = await manager.create_or_reject("thread-1", "focus-agent")
        await manager.set_status(first.run_id, RunStatus.RUNNING)
        cleanup_started = asyncio.Event()
        cleanup_release = asyncio.Event()
        cleanup_done = asyncio.Event()

        async def old_run():
            try:
                await asyncio.Event().wait()
            finally:
                cleanup_started.set()
                await cleanup_release.wait()
                cleanup_done.set()

        old_task = asyncio.create_task(old_run())
        await manager.attach_task(first.run_id, old_task)

        create_task = asyncio.create_task(
            manager.create_or_reject(
                "thread-1",
                "focus-agent",
                multitask_strategy=MultitaskStrategy.INTERRUPT,
            )
        )

        await asyncio.wait_for(cleanup_started.wait(), timeout=1)
        await asyncio.sleep(0)
        assert not create_task.done()

        cleanup_release.set()
        second = await asyncio.wait_for(create_task, timeout=1)

        assert second.run_id != first.run_id
        assert cleanup_done.is_set()
        assert old_task.done()

    asyncio.run(scenario())


def test_run_manager_interrupt_settle_handles_done_task_exception():
    async def scenario():
        manager = RunManager()
        first = await manager.create_or_reject("thread-1", "focus-agent")
        await manager.set_status(first.run_id, RunStatus.RUNNING)

        async def failed_run():
            raise RuntimeError("run failed before replacement")

        old_task = asyncio.create_task(failed_run())
        await asyncio.gather(old_task, return_exceptions=True)
        await manager.attach_task(first.run_id, old_task)

        second = await asyncio.wait_for(
            manager.create_or_reject(
                "thread-1",
                "focus-agent",
                multitask_strategy=MultitaskStrategy.ROLLBACK,
            ),
            timeout=1,
        )

        assert second.run_id != first.run_id
        assert first.abort_event.is_set()
        assert first.abort_action == "rollback"
        assert first.status is RunStatus.INTERRUPTED

    asyncio.run(scenario())


def test_run_manager_interrupt_settle_still_persists_status():
    class Store:
        def __init__(self):
            self.created = []
            self.statuses = []

        async def put(self, run_id, **kwargs):
            self.created.append((run_id, kwargs))

        async def update_status(self, run_id, status, *, error=None):
            self.statuses.append((run_id, status, error))

        async def update_run_completion(self, run_id, **kwargs):
            raise AssertionError("completion persistence should not be called")

    async def scenario():
        store = Store()
        manager = RunManager(store=store)
        first = await manager.create_or_reject("thread-1", "focus-agent")
        await manager.set_status(first.run_id, RunStatus.RUNNING)

        async def completed_run():
            return None

        old_task = asyncio.create_task(completed_run())
        await old_task
        await manager.attach_task(first.run_id, old_task)

        second = await manager.create_or_reject(
            "thread-1",
            "focus-agent",
            multitask_strategy=MultitaskStrategy.INTERRUPT,
        )

        assert [run_id for run_id, _ in store.created] == [first.run_id, second.run_id]
        assert (first.run_id, RunStatus.INTERRUPTED.value, None) in store.statuses

    asyncio.run(scenario())


def test_run_manager_rollback_waits_for_settle_before_handler():
    async def scenario():
        rolled_back = []

        async def rollback_handler(record):
            rolled_back.append(record.run_id)

        manager = RunManager(rollback_handler=rollback_handler)
        first = await manager.create_or_reject(
            "thread-1",
            "focus-agent",
            rollback_target=CheckpointRollbackTarget(
                thread_id="thread-1",
                checkpoint_ns="",
                checkpoint_id="checkpoint-1",
                metadata={},
            ),
        )
        await manager.set_status(first.run_id, RunStatus.RUNNING)
        cleanup_started = asyncio.Event()
        cleanup_release = asyncio.Event()

        async def old_run():
            try:
                await asyncio.Event().wait()
            finally:
                cleanup_started.set()
                await cleanup_release.wait()

        old_task = asyncio.create_task(old_run())
        await manager.attach_task(first.run_id, old_task)

        create_task = asyncio.create_task(
            manager.create_or_reject(
                "thread-1",
                "focus-agent",
                multitask_strategy=MultitaskStrategy.ROLLBACK,
            )
        )

        await asyncio.wait_for(cleanup_started.wait(), timeout=1)
        await asyncio.sleep(0)
        assert rolled_back == []

        cleanup_release.set()
        second = await asyncio.wait_for(create_task, timeout=1)

        assert second.run_id != first.run_id
        assert rolled_back == [first.run_id]

    asyncio.run(scenario())


def test_restore_graph_rollback_target_copies_baseline_checkpoint():
    class Graph:
        def __init__(self):
            self.update_calls = []

        def get_state(self, config):
            assert config == {"configurable": {"thread_id": "thread-1"}}
            return type(
                "Snapshot",
                (),
                {
                    "config": {
                        "configurable": {
                            "thread_id": "thread-1",
                            "checkpoint_ns": "",
                            "checkpoint_id": "checkpoint-1",
                        }
                    },
                    "metadata": {"source": "loop"},
                },
            )()

        def update_state(self, config, values, *, as_node):
            self.update_calls.append((config, values, as_node))
            return {"configurable": {"checkpoint_id": "checkpoint-rollback"}}

    async def scenario():
        graph = Graph()
        target = capture_checkpoint_rollback_target(graph, "thread-1")
        result = await restore_graph_rollback_target(graph, None, target)

        assert result.applied is True
        assert result.checkpoint_id == "checkpoint-rollback"
        assert graph.update_calls == [
            (
                {
                    "configurable": {
                        "thread_id": "thread-1",
                        "checkpoint_ns": "",
                        "checkpoint_id": "checkpoint-1",
                    }
                },
                [],
                "__copy__",
            )
        ]

    asyncio.run(scenario())


def test_restore_graph_rollback_target_deletes_empty_thread():
    class Checkpointer:
        def __init__(self):
            self.deleted = []

        def delete_thread(self, thread_id):
            self.deleted.append(thread_id)

    async def scenario():
        checkpointer = Checkpointer()
        result = await restore_graph_rollback_target(
            object(),
            checkpointer,
            CheckpointRollbackTarget(
                thread_id="thread-empty",
                checkpoint_ns="",
                checkpoint_id=None,
                metadata={},
            ),
        )

        assert result.applied is True
        assert result.reason == "deleted_thread"
        assert checkpointer.deleted == ["thread-empty"]

    asyncio.run(scenario())


def test_restore_graph_rollback_target_restores_persistent_langgraph_state(tmp_path):
    def append_one(state: _RollbackGraphState):
        del state
        return {"messages": ["one"]}

    saver = PersistentInMemorySaver(tmp_path / "checkpoints.pkl")
    builder = StateGraph(_RollbackGraphState)
    builder.add_node("append_one", append_one)
    builder.add_edge(START, "append_one")
    builder.add_edge("append_one", END)
    graph = builder.compile(checkpointer=saver)
    config = {"configurable": {"thread_id": "thread-1"}}

    graph.invoke({"messages": []}, config=config)
    target = capture_checkpoint_rollback_target(graph, "thread-1")
    graph.update_state(config, {"messages": ["two"]}, as_node="append_one")

    assert graph.get_state(config).values["messages"] == ["one", "two"]

    result = asyncio.run(restore_graph_rollback_target(graph, saver, target))

    assert result.applied is True
    assert graph.get_state(config).values["messages"] == ["one"]


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
