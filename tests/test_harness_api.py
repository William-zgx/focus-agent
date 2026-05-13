from __future__ import annotations

import asyncio
from types import SimpleNamespace

from langchain.messages import AIMessage, AIMessageChunk
from langgraph.types import Command

import focus_agent.api.routers.harness_runs as harness_runs
from focus_agent.harness.observability import InMemoryRunJournal, JournaledStreamBridge
from focus_agent.harness.runtime import RunStatus
from focus_agent.harness.runtime.rollback import (
    ROLLBACK_TARGET_METADATA_KEY,
    CheckpointRollbackTarget,
)
from focus_agent.harness.streaming import END_SENTINEL, InMemoryStreamBridge, StreamEvent


def test_prepare_resume_payload_uses_langgraph_command_resume():
    class _Chat:
        def _preflight_thread_access(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(root_thread_id="root-1"), {"branch": "main"}, {"messages": []}

    chat = _Chat()
    payload = harness_runs.HarnessResumeRequest(
        resume={"approved": True},
        metadata={"assistant_id": "focus-agent"},
    )

    command, context, branch_meta, initial_values = harness_runs._prepare_resume_payload(
        thread_id="thread-1",
        user_id="user-1",
        payload=payload,
        chat=chat,
    )

    assert isinstance(command, Command)
    assert command.resume == {"approved": True}
    assert context.root_thread_id == "root-1"
    assert branch_meta == {"branch": "main"}
    assert initial_values == {"messages": []}
    assert chat.kwargs == {
        "thread_id": "thread-1",
        "user_id": "user-1",
        "explicit_skill_hints": (),
        "require_writable": True,
    }


def test_get_persisted_run_reads_runtime_event_store_when_manager_misses():
    class _Run:
        def to_dict(self):
            return {"run_id": "run-1", "thread_id": "thread-1", "status": "success"}

    class _EventStore:
        async def get_run(self, run_id: str):
            assert run_id == "run-1"
            return _Run()

    async def scenario():
        runtime = SimpleNamespace(event_store=_EventStore())
        assert await harness_runs._get_persisted_run(runtime, "run-1") == {
            "run_id": "run-1",
            "thread_id": "thread-1",
            "status": "success",
        }

    asyncio.run(scenario())


def test_create_run_record_persists_user_id():
    class _RunManager:
        async def create_or_reject(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            return SimpleNamespace(run_id="run-1")

    async def scenario():
        manager = _RunManager()
        payload = harness_runs.HarnessRunRequest(message="hello")

        await harness_runs._create_run_record(
            runtime=SimpleNamespace(run_manager=manager),
            payload=payload,
            thread_id="thread-1",
            user_id="user-1",
            graph_payload={"messages": []},
            rollback_target=CheckpointRollbackTarget(
                thread_id="thread-1",
                checkpoint_ns="",
                checkpoint_id="checkpoint-1",
                metadata={},
            ),
        )

        assert manager.args == ("thread-1",)
        assert manager.kwargs["user_id"] == "user-1"
        assert manager.kwargs["rollback_target"].checkpoint_id == "checkpoint-1"
        assert manager.kwargs["metadata"][ROLLBACK_TARGET_METADATA_KEY] == {
            "thread_id": "thread-1",
            "checkpoint_ns": "",
            "checkpoint_id": "checkpoint-1",
        }

    asyncio.run(scenario())


def test_create_run_record_rejects_enqueue_with_422():
    class _RunManager:
        async def create_or_reject(self, *args, **kwargs):
            raise harness_runs.UnsupportedStrategyError("Multitask strategy 'enqueue' is not supported yet.")

    async def scenario():
        payload = harness_runs.HarnessRunRequest(message="hello", multitask_strategy="enqueue")
        try:
            await harness_runs._create_run_record(
                runtime=SimpleNamespace(run_manager=_RunManager()),
                payload=payload,
                thread_id="thread-1",
                user_id="user-1",
                graph_payload={"messages": []},
            )
        except harness_runs.HTTPException as exc:
            assert exc.status_code == 422
            assert "enqueue" in str(exc.detail)
        else:  # pragma: no cover
            raise AssertionError("expected unsupported strategy to map to HTTP 422")

    asyncio.run(scenario())


def test_create_run_record_marks_branch_action_rollback_partial():
    class _RunManager:
        async def create_or_reject(self, *args, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(run_id="run-1")

    async def scenario():
        manager = _RunManager()
        payload = harness_runs.HarnessRunRequest(message="hello")

        await harness_runs._create_run_record(
            runtime=SimpleNamespace(run_manager=manager),
            payload=payload,
            thread_id="thread-1",
            user_id="user-1",
            graph_payload={"messages": []},
            rollback_partial=True,
            rollback_unreverted_scopes=("branch_action",),
        )

        assert manager.kwargs["metadata"]["harness.rollback_partial"] is True
        assert manager.kwargs["metadata"]["harness.rollback_unreverted_scopes"] == ["branch_action"]

    asyncio.run(scenario())


def test_create_harness_run_uses_harness_invoke_adapter(monkeypatch):
    class _Selection:
        stripped_message = "hello"
        skill_ids = ()
        prompt_mode = None

    class _Chat:
        runtime = SimpleNamespace(settings=SimpleNamespace(model="model-1"))

        def _select_skills_for_message(self, **kwargs):
            self.selection_kwargs = kwargs
            return _Selection()

        def _preflight_thread_access(self, **kwargs):
            self.preflight_kwargs = kwargs
            return SimpleNamespace(root_thread_id="root-1"), {"branch": "main"}, {"messages": []}

        def _effective_thinking_mode(self, **kwargs):
            return "auto"

        def _branch_action_intent(self, **kwargs):
            return None

        def _context_for_thread(self, **kwargs):
            return SimpleNamespace(root_thread_id="root-1"), {"branch": "main"}, {"messages": []}

        def _safe_get_interrupts(self, thread_id: str):
            return []

        def _response_payload(self, **kwargs):
            return {"thread_id": kwargs["thread_id"]}

    class _RunManager:
        def __init__(self):
            self.record = SimpleNamespace(
                run_id="run-1",
                to_dict=lambda: {"run_id": "run-1", "thread_id": "thread-1", "status": "success"},
            )
            self.statuses = []

        async def create_or_reject(self, *args, **kwargs):
            return self.record

        async def set_status(self, run_id, status, **kwargs):
            self.statuses.append((run_id, status, kwargs))

        def get(self, run_id):
            return self.record

    class _Harness:
        graph = object()

        def __init__(self):
            self.invocations = []

        def invoke(self, payload, **kwargs):
            self.invocations.append((payload, kwargs))
            return {"messages": [AIMessage(content="done")]}

    class _GraphShouldNotRun:
        def invoke(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("API must invoke through runtime.harness")

    async def scenario():
        harness = _Harness()
        manager = _RunManager()
        runtime = SimpleNamespace(
            settings=SimpleNamespace(model="model-1"),
            harness=harness,
            graph=_GraphShouldNotRun(),
            run_manager=manager,
        )
        monkeypatch.setattr(harness_runs, "build_trace_correlation", lambda **kwargs: {})
        monkeypatch.setattr(harness_runs, "build_invoke_config", lambda **kwargs: {})

        response = await harness_runs.create_harness_run(
            thread_id="thread-1",
            payload=harness_runs.HarnessRunRequest(message="hello"),
            request=SimpleNamespace(state=SimpleNamespace(request_id="request-1")),
            runtime=runtime,
            chat=_Chat(),
            principal=SimpleNamespace(user_id="user-1"),
        )

        assert response.thread_state == {"thread_id": "thread-1"}
        assert harness.invocations
        assert harness.invocations[0][0]["task_brief"] == "hello"
        assert manager.statuses[-1][1] is RunStatus.SUCCESS

    asyncio.run(scenario())


def test_authorize_run_access_rejects_mismatched_user():
    class _Chat:
        def _preflight_thread_access(self, **kwargs):
            raise AssertionError("thread access should not run after user mismatch")

    principal = SimpleNamespace(user_id="user-2")

    try:
        harness_runs._authorize_run_access(
            chat=_Chat(),
            principal=principal,
            run_payload={"run_id": "run-1", "thread_id": "thread-1", "user_id": "user-1"},
        )
    except harness_runs.HTTPException as exc:
        assert exc.status_code == 403
    else:  # pragma: no cover
        raise AssertionError("expected authorization failure")


def test_stream_existing_harness_run_replays_with_last_event_id_without_cancelling():
    class _Run:
        def to_dict(self):
            return {
                "run_id": "run-1",
                "thread_id": "thread-1",
                "user_id": "user-1",
                "status": "running",
            }

    class _RunManager:
        def __init__(self):
            self.cancelled = False

        def get(self, run_id: str):
            assert run_id == "run-1"
            return _Run()

        async def cancel(self, *args, **kwargs):
            self.cancelled = True
            return True

    class _Bridge:
        def __init__(self):
            self.subscription = None

        async def subscribe(self, run_id: str, *, last_event_id: str | None, heartbeat_interval: float):
            self.subscription = {
                "run_id": run_id,
                "last_event_id": last_event_id,
                "heartbeat_interval": heartbeat_interval,
            }
            yield StreamEvent(
                id="evt-2",
                event="message.delta",
                data={
                    "run_id": "run-1",
                    "thread_id": "thread-1",
                    "turn_id": "run-1",
                    "sequence": 2,
                    "source_node": "agent",
                    "delta": "continued",
                },
            )
            yield END_SENTINEL

    class _Chat:
        def _preflight_thread_access(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(), None, {}

    async def scenario():
        manager = _RunManager()
        bridge = _Bridge()
        chat = _Chat()
        request = SimpleNamespace(headers={"last-event-id": "evt-1"})
        runtime = SimpleNamespace(
            run_manager=manager,
            event_store=None,
            stream_bridge=bridge,
            settings=SimpleNamespace(sse_heartbeat_seconds=7),
        )

        response = await harness_runs.stream_existing_harness_run(
            run_id="run-1",
            request=request,
            runtime=runtime,
            chat=chat,
            principal=SimpleNamespace(user_id="user-1"),
        )

        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)

        assert bridge.subscription == {
            "run_id": "run-1",
            "last_event_id": "evt-1",
            "heartbeat_interval": 7,
        }
        assert chat.kwargs["thread_id"] == "thread-1"
        assert "event: message.delta" in "".join(chunks)
        assert "continued" in "".join(chunks)
        assert manager.cancelled is False

    asyncio.run(scenario())


def test_harness_observability_endpoints_read_authorized_journal():
    class _Run:
        def to_dict(self):
            return {
                "run_id": "run-1",
                "thread_id": "thread-1",
                "user_id": "user-1",
                "status": "success",
            }

    class _RunManager:
        def get(self, run_id: str):
            assert run_id == "run-1"
            return _Run()

    class _Event:
        def to_dict(self):
            return {"event_id": "event-1", "run_id": "run-1", "event": "run.completed"}

    class _EventStore:
        async def list_events(self, run_id: str, *, event=None, limit=None):
            assert (run_id, event, limit) == ("run-1", "run.completed", 10)
            return [_Event()]

        async def snapshot(self, run_id: str):
            assert run_id == "run-1"
            return {"run": {"run_id": "run-1"}, "events": [{"event": "run.completed"}]}

        async def trajectory_summary(self, run_id: str):
            assert run_id == "run-1"
            return {"id": "run-1", "kind": "harness_run"}

    class _Chat:
        def _preflight_thread_access(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(), None, {}

    async def scenario():
        runtime = SimpleNamespace(run_manager=_RunManager(), event_store=_EventStore())
        chat = _Chat()
        principal = SimpleNamespace(user_id="user-1")

        events = await harness_runs.list_harness_run_events(
            "run-1",
            runtime=runtime,
            chat=chat,
            principal=principal,
            event="run.completed",
            limit=10,
        )
        snapshot = await harness_runs.get_harness_run_snapshot(
            "run-1",
            runtime=runtime,
            chat=chat,
            principal=principal,
        )
        trajectory = await harness_runs.get_harness_run_trajectory(
            "run-1",
            runtime=runtime,
            chat=chat,
            principal=principal,
        )

        assert events["events"] == [{"event_id": "event-1", "run_id": "run-1", "event": "run.completed"}]
        assert snapshot["run"]["run_id"] == "run-1"
        assert trajectory == {"id": "run-1", "kind": "harness_run"}
        assert chat.kwargs["thread_id"] == "thread-1"

    asyncio.run(scenario())


class _CollectingBridge:
    def __init__(self):
        self.events = []
        self.ended = False

    async def publish(self, run_id: str, event: str, data: dict):
        self.events.append((event, data))
        return SimpleNamespace(id=f"evt-{len(self.events)}", event=event, data=data)

    async def publish_end(self, run_id: str):
        self.ended = True


class _CollectingRunManager:
    def __init__(self):
        self.statuses = []
        self.record = SimpleNamespace(abort_event=asyncio.Event())

    def get(self, run_id: str):
        return self.record

    async def set_status(self, run_id: str, status: RunStatus, **kwargs):
        self.statuses.append((status, kwargs))


class _ProducerChat:
    def __init__(self, final_messages):
        self.final_messages = list(final_messages)

    def _context_for_thread(self, **kwargs):
        del kwargs
        return (
            SimpleNamespace(root_thread_id="root-1"),
            {"branch": "main"},
            {"messages": self.final_messages},
        )

    def _latest_final_ai_text(self, messages):
        for message in reversed(messages):
            content = getattr(message, "content", "")
            if content:
                return str(content)
        return ""

    def _safe_get_interrupts(self, thread_id: str):
        return []

    def _response_payload(self, **kwargs):
        return {"thread_id": kwargs["thread_id"], "messages": [{"type": "ai", "content": "done"}]}


_DEGRADED_DSML_FIXTURE = (
    "您说得对，让我把时间校准到当下，搜一下 2026 年的最新动态。好，拿到了几篇关键文章。\n\n"
    'invoke name">\n'
    'parameter name="" string="true">direct</ | | DSML | | parameter>\n'
    'parameter name="" string="true">https://mem0.ai/blog/state-of-ai-agent-memory-2026'
    "</ | | DSML | | parameter>\n"
    'parameter name="" string="false">2</ | | DSML | | parameter>\n'
    "</ | | DSML | | invoke>"
)


async def _collect_produced_events(monkeypatch, chunks, *, final_messages=None, error: Exception | None = None):
    async def fake_stream_chunks(**kwargs):
        del kwargs
        if error is not None:
            raise error
        for chunk in chunks:
            yield chunk

    class _Harness:
        graph = object()

        def __init__(self):
            self.called = False

        async def stream_chunks(self, **kwargs):
            self.called = True
            assert kwargs["payload"] == {"messages": []}
            async for chunk in fake_stream_chunks(**kwargs):
                yield chunk

    bridge = _CollectingBridge()
    manager = _CollectingRunManager()
    runtime = SimpleNamespace(
        harness=_Harness(),
        checkpointer=None,
        settings=SimpleNamespace(sse_heartbeat_seconds=0),
        run_manager=manager,
        stream_bridge=bridge,
    )

    monkeypatch.setattr(harness_runs, "build_trace_correlation", lambda **kwargs: {})
    monkeypatch.setattr(harness_runs, "build_invoke_config", lambda **kwargs: {})

    producer_final_messages = [AIMessage(content="done")] if final_messages is None else final_messages

    await harness_runs._produce_run_stream(
        runtime=runtime,
        chat=_ProducerChat(producer_final_messages),
        run_id="run-1",
        thread_id="thread-1",
        user_id="user-1",
        payload={"messages": []},
        context=SimpleNamespace(root_thread_id="root-1"),
        branch_meta={"branch": "main"},
        initial_values={"messages": []},
        request_id="request-1",
    )
    return bridge.events, manager.statuses, bridge.ended


def test_produce_run_stream_emits_canonical_v2_events(monkeypatch):
    async def fake_stream_chunks(**kwargs):
        del kwargs
        yield {
            "type": "messages",
            "data": (
                SimpleNamespace(content="hello", type="ai", id="msg-1"),
                {"langgraph_node": "agent", "stream_phase": "visible"},
            ),
            "ns": [],
        }

    class _Harness:
        graph = object()

        def __init__(self):
            self.called = False

        async def stream_chunks(self, **kwargs):
            self.called = True
            assert kwargs["payload"] == {"messages": []}
            async for chunk in fake_stream_chunks(**kwargs):
                yield chunk

    class _Bridge:
        def __init__(self):
            self.events = []
            self.ended = False

        async def publish(self, run_id: str, event: str, data: dict):
            self.events.append((event, data))
            return SimpleNamespace(id=f"evt-{len(self.events)}", event=event, data=data)

        async def publish_end(self, run_id: str):
            self.ended = True

    class _Manager:
        def __init__(self):
            self.statuses = []
            self.record = SimpleNamespace(abort_event=asyncio.Event())

        def get(self, run_id: str):
            return self.record

        async def set_status(self, run_id: str, status: RunStatus, **kwargs):
            self.statuses.append((status, kwargs))

    class _Chat:
        def _context_for_thread(self, **kwargs):
            del kwargs
            return (
                SimpleNamespace(root_thread_id="root-1"),
                {"branch": "main"},
                {"messages": [AIMessage(content="done")]},
            )

        def _latest_final_ai_text(self, messages):
            for message in reversed(messages):
                content = getattr(message, "content", "")
                if content:
                    return str(content)
            return ""

        def _safe_get_interrupts(self, thread_id: str):
            return []

        def _response_payload(self, **kwargs):
            return {"thread_id": kwargs["thread_id"], "messages": [{"type": "ai", "content": "done"}]}

    async def scenario():
        bridge = _Bridge()
        manager = _Manager()
        harness = _Harness()
        runtime = SimpleNamespace(
            harness=harness,
            checkpointer=None,
            settings=SimpleNamespace(sse_heartbeat_seconds=0),
            run_manager=manager,
            stream_bridge=bridge,
        )

        monkeypatch.setattr(harness_runs, "build_trace_correlation", lambda **kwargs: {})
        monkeypatch.setattr(harness_runs, "build_invoke_config", lambda **kwargs: {})

        await harness_runs._produce_run_stream(
            runtime=runtime,
            chat=_Chat(),
            run_id="run-1",
            thread_id="thread-1",
            user_id="user-1",
            payload={"messages": []},
            context=SimpleNamespace(root_thread_id="root-1"),
            branch_meta={"branch": "main"},
            initial_values={"messages": []},
            request_id="request-1",
        )

        event_names = [event for event, _data in bridge.events]
        assert "visible_text.delta" not in event_names
        assert event_names == [
            "run.metadata",
            "run.status",
            "message.delta",
            "message.completed",
            "run.completed",
            "run.closed",
        ]
        assert bridge.events[2][1]["delta"] == "hello"
        assert bridge.events[2][1]["message_id"] == "msg-1"
        assert "stream_phase" not in bridge.events[2][1]["metadata"]
        assert bridge.events[3][1]["content"] == "done"
        assert bridge.events[4][1]["thread_state"]["thread_id"] == "thread-1"
        assert bridge.events[-1][1]["source_node"] == "harness"
        assert bridge.ended is True
        assert harness.called is True
        assert manager.statuses[-1][0] is RunStatus.SUCCESS

    asyncio.run(scenario())


def test_produce_branch_action_run_stream_emits_canonical_completion():
    class _Chat:
        def __init__(self):
            self.kwargs = None

        def _handle_branch_action_turn(self, **kwargs):
            self.kwargs = kwargs
            return {
                "kind": "executed",
                "message": "已切换到新分支。",
                "thread_state": {"thread_id": "thread-1", "branch_actions": []},
                "branch_action": {"action_id": "action-1", "status": "executed"},
                "branch_record": {"branch_id": "branch-2"},
                "navigation": {"root_thread_id": "root-1", "thread_id": "thread-2"},
            }

    async def scenario():
        bridge = _CollectingBridge()
        manager = _CollectingRunManager()
        runtime = SimpleNamespace(run_manager=manager, stream_bridge=bridge)
        chat = _Chat()

        await harness_runs._produce_branch_action_run_stream(
            runtime=runtime,
            chat=chat,
            run_id="run-1",
            thread_id="thread-1",
            user_id="user-1",
            message="直接切过去",
            request_id="request-1",
        )

        event_names = [event for event, _data in bridge.events]
        assert "visible_text.delta" not in event_names
        assert event_names == [
            "run.metadata",
            "run.status",
            "message.completed",
            "run.completed",
            "run.closed",
        ]
        assert chat.kwargs == {
            "thread_id": "thread-1",
            "user_id": "user-1",
            "message": "直接切过去",
            "request_id": "request-1",
        }
        assert bridge.events[2][1]["content"] == "已切换到新分支。"
        completed = bridge.events[3][1]
        assert completed["thread_state"]["thread_id"] == "thread-1"
        assert completed["branch_action"]["action_id"] == "action-1"
        assert completed["branch_record"]["branch_id"] == "branch-2"
        assert completed["navigation"] == {"root_thread_id": "root-1", "thread_id": "thread-2"}
        assert bridge.ended is True
        assert manager.statuses[-1][0] is RunStatus.SUCCESS

    asyncio.run(scenario())


def test_produce_branch_action_run_stream_drops_tool_protocol_message():
    class _Chat:
        def _handle_branch_action_turn(self, **kwargs):
            del kwargs
            return {
                "kind": "executed",
                "message": "invoke name\nparameter name\n| | DSML | |",
                "thread_state": {"thread_id": "thread-1", "branch_actions": []},
            }

    async def scenario():
        bridge = _CollectingBridge()
        manager = _CollectingRunManager()
        runtime = SimpleNamespace(run_manager=manager, stream_bridge=bridge)

        await harness_runs._produce_branch_action_run_stream(
            runtime=runtime,
            chat=_Chat(),
            run_id="run-1",
            thread_id="thread-1",
            user_id="user-1",
            message="直接切过去",
            request_id="request-1",
        )

        event_names = [event for event, _data in bridge.events]

        assert "message.completed" not in event_names
        assert "run.completed" in event_names
        assert manager.statuses[-1][0] is RunStatus.SUCCESS

    asyncio.run(scenario())


def test_branch_action_intent_for_run_delegates_to_chat_facade():
    class _Chat:
        def _branch_action_intent(self, **kwargs):
            self.kwargs = kwargs
            return "propose"

    chat = _Chat()

    assert harness_runs._branch_action_intent_for_run(
        chat=chat,
        initial_values={"branch_actions": []},
        branch_meta={"branch": "main"},
        message="开个分支",
    )
    assert chat.kwargs == {
        "values": {"branch_actions": []},
        "branch_meta": {"branch": "main"},
        "message": "开个分支",
    }


def test_produce_run_stream_filters_internal_and_tool_fallback_drafts(monkeypatch):
    chunks = [
        {
            "type": "messages",
            "data": (
                SimpleNamespace(content='{"expected_tools":["search"],"status":"replan"}', type="ai"),
                {"langgraph_node": "plan"},
            ),
            "ns": [],
        },
        {
            "type": "messages",
            "data": (
                SimpleNamespace(content="我先根据已拿到的工具结果给出一个保守整理：\n- web_search: interim", type="ai"),
                {"langgraph_node": "agent"},
            ),
            "ns": [],
        },
        {
            "type": "messages",
            "data": (
                SimpleNamespace(content="真正回答", type="ai"),
                {"langgraph_node": "agent", "stream_phase": "visible"},
            ),
            "ns": [],
        },
    ]

    async def scenario():
        events, _statuses, _ended = await _collect_produced_events(
            monkeypatch,
            chunks,
            final_messages=[AIMessage(content="真正回答最终。")],
        )
        message_deltas = [data["delta"] for event, data in events if event == "message.delta"]
        completed = [data["content"] for event, data in events if event == "message.completed"]

        assert message_deltas == ["真正回答"]
        assert completed == ["真正回答最终。"]

    asyncio.run(scenario())


def test_produce_run_stream_quarantines_unmarked_and_quarantine_agent_text(monkeypatch):
    chunks = [
        {
            "type": "messages",
            "data": (
                SimpleNamespace(content="未标记的阶段文本", type="ai"),
                {"langgraph_node": "agent"},
            ),
            "ns": [],
        },
        {
            "type": "messages",
            "data": (
                SimpleNamespace(content=_DEGRADED_DSML_FIXTURE, type="ai"),
                {"langgraph_node": "agent", "stream_phase": "quarantine"},
            ),
            "ns": [],
        },
    ]

    async def scenario():
        events, _statuses, _ended = await _collect_produced_events(
            monkeypatch,
            chunks,
            final_messages=[AIMessage(content="最终安全回答。")],
        )
        message_deltas = [data["delta"] for event, data in events if event == "message.delta"]
        completed = [data["content"] for event, data in events if event == "message.completed"]

        assert message_deltas == []
        assert completed == ["最终安全回答。"]

    asyncio.run(scenario())


def test_produce_run_stream_drops_visible_phase_english_process_narration(monkeypatch):
    chunks = [
        {
            "type": "messages",
            "data": (
                SimpleNamespace(content="Let me fetch the latest numbers before answering.", type="ai"),
                {"langgraph_node": "agent", "stream_phase": "visible"},
            ),
            "ns": [],
        },
        {
            "type": "messages",
            "data": (
                SimpleNamespace(content="最终安全回答", type="ai"),
                {"langgraph_node": "agent", "stream_phase": "visible"},
            ),
            "ns": [],
        },
    ]

    async def scenario():
        events, _statuses, _ended = await _collect_produced_events(
            monkeypatch,
            chunks,
            final_messages=[AIMessage(content="最终安全回答。")],
        )
        message_deltas = [data["delta"] for event, data in events if event == "message.delta"]
        completed = [data["content"] for event, data in events if event == "message.completed"]

        assert message_deltas == ["最终安全回答"]
        assert completed == ["最终安全回答。"]

    asyncio.run(scenario())


def test_produce_run_stream_drops_split_visible_phase_english_process_narration(monkeypatch):
    chunks = [
        {
            "type": "messages",
            "data": (
                SimpleNamespace(content="Let", type="ai"),
                {"langgraph_node": "agent", "stream_phase": "visible"},
            ),
            "ns": [],
        },
        {
            "type": "messages",
            "data": (
                SimpleNamespace(content=" me fetch the latest source.", type="ai"),
                {"langgraph_node": "agent", "stream_phase": "visible"},
            ),
            "ns": [],
        },
    ]

    async def scenario():
        events, _statuses, _ended = await _collect_produced_events(
            monkeypatch,
            chunks=chunks,
            final_messages=[],
        )
        event_names = [event for event, _data in events]

        assert "message.delta" not in event_names
        assert "message.completed" not in event_names

    asyncio.run(scenario())


def test_produce_run_stream_streams_final_suffix_from_mixed_visible_process_text(monkeypatch):
    chunks = [
        {
            "type": "messages",
            "data": (
                SimpleNamespace(
                    content="Let me produce the final answer. I must not call more tools. Let's go.最终答案。",
                    type="ai",
                ),
                {"langgraph_node": "agent", "stream_phase": "visible"},
            ),
            "ns": [],
        },
    ]

    async def scenario():
        events, _statuses, _ended = await _collect_produced_events(
            monkeypatch,
            chunks=chunks,
            final_messages=[
                AIMessage(content="Let me produce the final answer. I must not call more tools. Let's go.最终答案。")
            ],
        )
        message_deltas = [data["delta"] for event, data in events if event == "message.delta"]
        completed = [data["content"] for event, data in events if event == "message.completed"]

        assert message_deltas == ["最终答案。"]
        assert completed == ["最终答案。"]

    asyncio.run(scenario())


def test_produce_run_stream_drops_english_process_completed_fallback(monkeypatch):
    async def scenario():
        events, _statuses, _ended = await _collect_produced_events(
            monkeypatch,
            chunks=[],
            final_messages=[AIMessage(content="I should look up one more source before answering.")],
        )

        assert "message.completed" not in [event for event, _data in events]

    asyncio.run(scenario())


def test_produce_run_stream_visible_phase_allows_text_and_keeps_tool_events(monkeypatch):
    chunks = [
        {
            "type": "messages",
            "data": (
                AIMessageChunk(
                    content=[
                        {
                            "type": "tool_call_chunk",
                            "id": "call-1",
                            "name": "web_search",
                            "args": '{"q":"agent"}',
                        }
                    ]
                ),
                {"langgraph_node": "agent", "stream_phase": "quarantine"},
            ),
            "ns": [],
        },
        {
            "type": "messages",
            "data": (
                SimpleNamespace(content="最终回答", type="ai"),
                {"langgraph_node": "agent", "tags": ["stream_phase:visible", "demo"]},
            ),
            "ns": [],
        },
    ]

    async def scenario():
        events, _statuses, _ended = await _collect_produced_events(
            monkeypatch,
            chunks,
            final_messages=[AIMessage(content="最终回答。")],
        )
        event_names = [event for event, _data in events]
        message_deltas = [data["delta"] for event, data in events if event == "message.delta"]
        tool_payload = next(data for event, data in events if event == "tool.call.delta")
        message_delta_payload = next(data for event, data in events if event == "message.delta")

        assert "tool.call.delta" in event_names
        assert message_deltas == ["最终回答"]
        assert tool_payload["tool_call_id"] == "call-1"
        assert message_delta_payload["metadata"]["tags"] == ["demo"]

    asyncio.run(scenario())


def test_produce_run_stream_drops_tool_protocol_completed_fallback(monkeypatch):
    async def scenario():
        events, _statuses, _ended = await _collect_produced_events(
            monkeypatch,
            chunks=[],
            final_messages=[AIMessage(content=_DEGRADED_DSML_FIXTURE)],
        )

        assert "message.completed" not in [event for event, _data in events]

    asyncio.run(scenario())


def test_produce_run_stream_drops_split_tool_protocol_stream_buffer(monkeypatch):
    chunks = [
        {
            "type": "messages",
            "data": (
                SimpleNamespace(content="tool", type="ai"),
                {"langgraph_node": "agent", "stream_phase": "visible"},
            ),
            "ns": [],
        },
        {
            "type": "messages",
            "data": (
                SimpleNamespace(content='calls/invoke namewebfetch">\nparameter name=""', type="ai"),
                {"langgraph_node": "agent", "stream_phase": "visible"},
            ),
            "ns": [],
        },
    ]

    async def scenario():
        events, _statuses, _ended = await _collect_produced_events(
            monkeypatch,
            chunks=chunks,
            final_messages=[],
        )
        event_names = [event for event, _data in events]

        assert "message.delta" not in event_names
        assert "message.completed" not in event_names

    asyncio.run(scenario())


def test_produce_run_stream_drops_split_degraded_invoke_name_stream_buffer(monkeypatch):
    chunks = [
        {
            "type": "messages",
            "data": (
                SimpleNamespace(content="invoke", type="ai"),
                {"langgraph_node": "agent", "stream_phase": "visible"},
            ),
            "ns": [],
        },
        {
            "type": "messages",
            "data": (
                SimpleNamespace(
                    content=(
                        " name 2025 trends predictions multi-agent collaboration future</ | | DSML | | parameter>\n"
                        "parameter name6</ | | DSML | | parameter>"
                    ),
                    type="ai",
                ),
                {"langgraph_node": "agent", "stream_phase": "visible"},
            ),
            "ns": [],
        },
    ]

    async def scenario():
        events, _statuses, _ended = await _collect_produced_events(
            monkeypatch,
            chunks=chunks,
            final_messages=[],
        )
        event_names = [event for event, _data in events]

        assert "message.delta" not in event_names
        assert "message.completed" not in event_names

    asyncio.run(scenario())


def test_produce_run_stream_holds_split_dsml_prefix_stream_buffer(monkeypatch):
    chunks = [
        {
            "type": "messages",
            "data": (
                SimpleNamespace(content="< | | ", type="ai"),
                {"langgraph_node": "agent", "stream_phase": "visible"},
            ),
            "ns": [],
        },
        {
            "type": "messages",
            "data": (
                SimpleNamespace(content="DSML | | invoke nameweb_search", type="ai"),
                {"langgraph_node": "agent", "stream_phase": "visible"},
            ),
            "ns": [],
        },
    ]

    async def scenario():
        events, _statuses, _ended = await _collect_produced_events(
            monkeypatch,
            chunks=chunks,
            final_messages=[],
        )
        event_names = [event for event, _data in events]

        assert "message.delta" not in event_names
        assert "message.completed" not in event_names

    asyncio.run(scenario())


def test_produce_run_stream_drops_degraded_xmlish_tool_c_stream_buffer(monkeypatch):
    chunks = [
        {
            "type": "messages",
            "data": (
                SimpleNamespace(content="<tool", type="ai"),
                {"langgraph_node": "agent", "stream_phase": "visible"},
            ),
            "ns": [],
        },
        {
            "type": "messages",
            "data": (
                SimpleNamespace(
                    content=(
                        '_c>\n<invoke="web_fetch">\n'
                        '<parameterurl" string="true">https://vectorize.io/articles/best-ai-agent-memory-systems</parameter>'
                    ),
                    type="ai",
                ),
                {"langgraph_node": "agent", "stream_phase": "visible"},
            ),
            "ns": [],
        },
    ]

    async def scenario():
        events, _statuses, _ended = await _collect_produced_events(
            monkeypatch,
            chunks=chunks,
            final_messages=[],
        )
        event_names = [event for event, _data in events]

        assert "message.delta" not in event_names
        assert "message.completed" not in event_names

    asyncio.run(scenario())


def test_produce_run_stream_drops_orphaned_protocol_tail_stream_buffer(monkeypatch):
    chunks = [
        {
            "type": "messages",
            "data": (
                SimpleNamespace(
                    content=(
                        'alls>\n="web_search">\n'
                        '="query" string="true">AI agent predictions 2026\n'
                        '="query"true">AI agent frameworks comparison 2026 pros cons LangChain CrewAI AutoGen\n'
                        '="url"true">https://alicelabs.ai/en/insights/best-ai-agent-frameworks-2026\n'
                        '="web_fetch="url" string="true">https://www.gartner.com/en/articles\n'
                        '="max_chars" stringfalse">8000\n'
                        '="max_chars"false">6000\n'
                        "https://www.shrutigupta01.com/ai-agent-frameworks-in-2026/parameter>\n"
                        "12000parameter>\n"
                        '="max_fetch_length" stringfalse8000parameter>\n'
                        "invoke>\n"
                        '="read="filepath" string="true">tool-observation://webfetch/'
                        "call00ljJOwoeUmsjmBzMNhkx8505\n"
                        "</ | | DSML | | tool_calls"
                    ),
                    type="ai",
                ),
                {"langgraph_node": "agent", "stream_phase": "visible"},
            ),
            "ns": [],
        },
    ]

    async def scenario():
        events, _statuses, _ended = await _collect_produced_events(
            monkeypatch,
            chunks=chunks,
            final_messages=[],
        )
        event_names = [event for event, _data in events]

        assert "message.delta" not in event_names
        assert "message.completed" not in event_names

    asyncio.run(scenario())


def test_produce_run_stream_holds_split_degraded_assignment_tail(monkeypatch):
    chunks = [
        {
            "type": "messages",
            "data": (
                SimpleNamespace(content="=", type="ai"),
                {"langgraph_node": "agent", "stream_phase": "visible"},
            ),
            "ns": [],
        },
        {
            "type": "messages",
            "data": (
                SimpleNamespace(content='"read=', type="ai"),
                {"langgraph_node": "agent", "stream_phase": "visible"},
            ),
            "ns": [],
        },
        {
            "type": "messages",
            "data": (
                SimpleNamespace(
                    content='"filepath" string="true">tool-observation://webfetch/call00ljJOwoeUmsjmBzMNhkx8505',
                    type="ai",
                ),
                {"langgraph_node": "agent", "stream_phase": "visible"},
            ),
            "ns": [],
        },
    ]

    async def scenario():
        events, _statuses, _ended = await _collect_produced_events(
            monkeypatch,
            chunks=chunks,
            final_messages=[],
        )
        event_names = [event for event, _data in events]

        assert "message.delta" not in event_names
        assert "message.completed" not in event_names

    asyncio.run(scenario())


def test_produce_run_stream_drops_compacted_parameter_assignment_tail(monkeypatch):
    chunks = [
        {
            "type": "messages",
            "data": (
                SimpleNamespace(content='="url"', type="ai"),
                {"langgraph_node": "agent", "stream_phase": "visible"},
            ),
            "ns": [],
        },
        {
            "type": "messages",
            "data": (
                SimpleNamespace(
                    content='true">https://alicelabs.ai/en/insights/best-ai-agent-frameworks-2026',
                    type="ai",
                ),
                {"langgraph_node": "agent", "stream_phase": "visible"},
            ),
            "ns": [],
        },
        {
            "type": "messages",
            "data": (
                SimpleNamespace(
                    content='</｜｜DSML｜｜parameter>\n="max_chars"false">6000',
                    type="ai",
                ),
                {"langgraph_node": "agent", "stream_phase": "visible"},
            ),
            "ns": [],
        },
    ]

    async def scenario():
        events, _statuses, _ended = await _collect_produced_events(
            monkeypatch,
            chunks=chunks,
            final_messages=[],
        )
        event_names = [event for event, _data in events]

        assert "message.delta" not in event_names
        assert "message.completed" not in event_names

    asyncio.run(scenario())


def test_produce_run_stream_drops_bare_dsml_completed_fallback(monkeypatch):
    async def scenario():
        events, _statuses, _ended = await _collect_produced_events(
            monkeypatch,
            chunks=[],
            final_messages=[AIMessage(content="invoke name\nparameter name\n| | DSML | |")],
        )

        assert "message.completed" not in [event for event, _data in events]

    asyncio.run(scenario())


def test_produce_run_stream_drops_textual_tool_protocol_reasoning(monkeypatch):
    chunks = [
        {
            "type": "messages",
            "data": (
                SimpleNamespace(
                    content=[
                        {
                            "type": "reasoning_delta",
                            "text": 'invoke name">\nparameter name="" string="true">direct',
                        }
                    ],
                    type="ai",
                ),
                {"langgraph_node": "agent"},
            ),
            "ns": [],
        },
        {
            "type": "messages",
            "data": (
                SimpleNamespace(
                    content=[{"type": "reasoning_delta", "text": "safe reasoning"}],
                    type="ai",
                ),
                {"langgraph_node": "agent"},
            ),
            "ns": [],
        },
    ]

    async def scenario():
        events, _statuses, _ended = await _collect_produced_events(
            monkeypatch,
            chunks=chunks,
            final_messages=[AIMessage(content="最终安全回答。")],
        )
        reasoning_deltas = [data["delta"] for event, data in events if event == "reasoning.delta"]

        assert reasoning_deltas == ["safe reasoning", ""]

    asyncio.run(scenario())


def test_produce_run_stream_drops_split_tool_protocol_reasoning(monkeypatch):
    chunks = [
        {
            "type": "messages",
            "data": (
                SimpleNamespace(content=[{"type": "reasoning_delta", "text": "tool"}], type="ai"),
                {"langgraph_node": "agent"},
            ),
            "ns": [],
        },
        {
            "type": "messages",
            "data": (
                SimpleNamespace(
                    content=[
                        {
                            "type": "reasoning_delta",
                            "text": 'calls/invoke namewebfetch">\nparameter name=""',
                        }
                    ],
                    type="ai",
                ),
                {"langgraph_node": "agent"},
            ),
            "ns": [],
        },
    ]

    async def scenario():
        events, _statuses, _ended = await _collect_produced_events(
            monkeypatch,
            chunks=chunks,
            final_messages=[AIMessage(content="最终安全回答。")],
        )
        reasoning_deltas = [data["delta"] for event, data in events if event == "reasoning.delta"]

        assert reasoning_deltas == []

    asyncio.run(scenario())


def test_produce_run_stream_emits_tool_call_delta_without_legacy_alias(monkeypatch):
    chunks = [
        {
            "type": "messages",
            "data": (
                AIMessageChunk(
                    content=[
                        {
                            "type": "tool_call_chunk",
                            "id": "call-1",
                            "name": "search_web",
                            "args": '{"q":"agent"}',
                        }
                    ]
                ),
                {"langgraph_node": "agent"},
            ),
            "ns": [],
        }
    ]

    async def scenario():
        events, _statuses, _ended = await _collect_produced_events(monkeypatch, chunks)
        event_names = [event for event, _data in events]
        tool_payload = next(data for event, data in events if event == "tool.call.delta")

        assert "tool_call.delta" not in event_names
        assert "message.delta" not in event_names
        assert tool_payload["tool_call_id"] == "call-1"
        assert tool_payload["name"] == "search_web"

    asyncio.run(scenario())


def test_produce_run_stream_accepts_custom_tool_payload_event_key(monkeypatch):
    chunks = [
        {
            "type": "custom",
            "data": {
                "event": "tool",
                "stage": "start",
                "tool_call_id": "call-1",
                "tool_name": "web_search",
                "source_node": "payload-source-should-not-override-canonical",
            },
            "ns": ["agent"],
        }
    ]

    async def scenario():
        events, statuses, ended = await _collect_produced_events(monkeypatch, chunks)
        event_names = [event for event, _data in events]
        tool_payload = next(data for event, data in events if event == "tool.requested")

        assert "run.failed" not in event_names
        assert tool_payload["event"] == "tool"
        assert tool_payload["tool_call_id"] == "call-1"
        assert tool_payload["tool_name"] == "web_search"
        assert tool_payload["source_node"] == "agent"
        assert statuses[-1][0] is RunStatus.SUCCESS
        assert ended is True

    asyncio.run(scenario())


def test_produce_run_stream_demotes_custom_tool_payload_without_call_id(monkeypatch):
    chunks = [
        {
            "type": "custom",
            "data": {
                "event": "tool",
                "stage": "start",
                "tool_name": "web_search",
            },
            "ns": ["agent"],
        }
    ]

    async def scenario():
        events, statuses, ended = await _collect_produced_events(monkeypatch, chunks)
        event_names = [event for event, _data in events]
        state_payload = next(
            data
            for event, data in events
            if event == "state.update" and data.get("event") == "tool"
        )

        assert "tool.requested" not in event_names
        assert state_payload["tool_name"] == "web_search"
        assert statuses[-1][0] is RunStatus.SUCCESS
        assert ended is True

    asyncio.run(scenario())


def test_produce_run_stream_reports_exception_as_run_failed(monkeypatch):
    async def scenario():
        events, statuses, ended = await _collect_produced_events(
            monkeypatch,
            [],
            error=RuntimeError("stream failed for test"),
        )
        by_name = {event: data for event, data in events}

        assert by_name["run.failed"] == {
            "run_id": "run-1",
            "thread_id": "thread-1",
            "turn_id": "run-1",
            "sequence": 3,
            "source_node": "harness",
            "error": "RuntimeError",
            "message": "stream failed for test",
        }
        assert events[-1][0] == "run.closed"
        assert statuses[-1][0] is RunStatus.ERROR
        assert ended is True

    asyncio.run(scenario())


def test_produce_run_stream_does_not_duplicate_manager_interrupt(monkeypatch):
    async def fake_stream_chunks(**kwargs):
        del kwargs
        raise asyncio.CancelledError
        yield  # pragma: no cover

    class _Harness:
        graph = object()

        async def stream_chunks(self, **kwargs):
            async for chunk in fake_stream_chunks(**kwargs):
                yield chunk

    class _Bridge:
        def __init__(self):
            self.events = []

        async def publish(self, run_id: str, event: str, data: dict):
            self.events.append((event, data))
            return SimpleNamespace(id=f"evt-{len(self.events)}", event=event, data=data)

        async def publish_end(self, run_id: str):
            self.ended = True

    class _Manager:
        def __init__(self):
            abort_event = asyncio.Event()
            abort_event.set()
            self.record = SimpleNamespace(abort_event=abort_event, abort_action="interrupt")
            self.statuses = []

        def get(self, run_id: str):
            return self.record

        async def set_status(self, run_id: str, status: RunStatus, **kwargs):
            self.statuses.append((status, kwargs))

    async def scenario():
        bridge = _Bridge()
        runtime = SimpleNamespace(
            harness=_Harness(),
            checkpointer=None,
            settings=SimpleNamespace(sse_heartbeat_seconds=0),
            run_manager=_Manager(),
            stream_bridge=bridge,
        )

        monkeypatch.setattr(harness_runs, "build_trace_correlation", lambda **kwargs: {})
        monkeypatch.setattr(harness_runs, "build_invoke_config", lambda **kwargs: {})

        await harness_runs._produce_run_stream(
            runtime=runtime,
            chat=SimpleNamespace(),
            run_id="run-1",
            thread_id="thread-1",
            user_id="user-1",
            payload={"messages": []},
            context=SimpleNamespace(root_thread_id="root-1"),
            branch_meta={"branch": "main"},
            initial_values={"messages": []},
            request_id="request-1",
        )

        event_names = [event for event, _data in bridge.events]
        assert "run.failed" not in event_names
        assert event_names[-1] == "run.closed"
        assert "run.interrupt" not in event_names

    asyncio.run(scenario())


def test_produce_run_stream_keeps_closed_sequence_after_lifecycle_event(monkeypatch):
    async def fake_stream_chunks(**kwargs):
        del kwargs
        raise asyncio.CancelledError
        yield  # pragma: no cover

    class _Harness:
        graph = object()

        async def stream_chunks(self, **kwargs):
            async for chunk in fake_stream_chunks(**kwargs):
                yield chunk

    class _Manager:
        def __init__(self, bridge, journal):
            abort_event = asyncio.Event()
            abort_event.set()
            self.record = SimpleNamespace(abort_event=abort_event, abort_action="interrupt")
            self.bridge = bridge
            self.journal = journal
            self.published_interrupt = False

        def get(self, run_id: str):
            return self.record

        async def set_status(self, run_id: str, status: RunStatus, **kwargs):
            del kwargs
            if status is RunStatus.INTERRUPTED and not self.published_interrupt:
                self.published_interrupt = True
                sequence = await self.journal.count_events(run_id) + 1
                await self.bridge.publish(
                    run_id,
                    "run.interrupt",
                    harness_runs.canonical_event_payload(
                        run_id=run_id,
                        thread_id="thread-1",
                        turn_id=run_id,
                        sequence=sequence,
                        action="interrupt",
                    ),
                )

    async def scenario():
        journal = InMemoryRunJournal()
        await journal.put("run-1", thread_id="thread-1", status="running")
        bridge = JournaledStreamBridge(
            journal=journal,
            bridge=InMemoryStreamBridge(max_buffer_size=10),
        )
        runtime = SimpleNamespace(
            event_store=journal,
            harness=_Harness(),
            checkpointer=None,
            settings=SimpleNamespace(sse_heartbeat_seconds=0),
            stream_bridge=bridge,
        )
        runtime.run_manager = _Manager(bridge, journal)

        monkeypatch.setattr(harness_runs, "build_trace_correlation", lambda **kwargs: {})
        monkeypatch.setattr(harness_runs, "build_invoke_config", lambda **kwargs: {})

        await harness_runs._produce_run_stream(
            runtime=runtime,
            chat=SimpleNamespace(),
            run_id="run-1",
            thread_id="thread-1",
            user_id="user-1",
            payload={"messages": []},
            context=SimpleNamespace(root_thread_id="root-1"),
            branch_meta={"branch": "main"},
            initial_values={"messages": []},
            request_id="request-1",
        )

        events = await journal.list_events("run-1")
        assert [event.event for event in events] == [
            "run.metadata",
            "run.status",
            "run.interrupt",
            "run.closed",
        ]
        assert [event.data["sequence"] for event in events] == [1, 2, 3, 4]

    asyncio.run(scenario())
