from __future__ import annotations

import asyncio
from types import SimpleNamespace

from langchain.messages import AIMessage, AIMessageChunk
from langgraph.types import Command

import focus_agent.api.routers.harness_runs as harness_runs
from focus_agent.harness.runtime import RunStatus


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


async def _collect_produced_events(monkeypatch, chunks, *, final_messages=None, error: Exception | None = None):
    async def fake_stream_graph_chunks(**kwargs):
        del kwargs
        if error is not None:
            raise error
        for chunk in chunks:
            yield chunk

    bridge = _CollectingBridge()
    manager = _CollectingRunManager()
    runtime = SimpleNamespace(
        graph=object(),
        checkpointer=None,
        settings=SimpleNamespace(sse_heartbeat_seconds=0),
        run_manager=manager,
        stream_bridge=bridge,
    )

    monkeypatch.setattr(harness_runs, "stream_graph_chunks", fake_stream_graph_chunks)
    monkeypatch.setattr(harness_runs, "build_trace_correlation", lambda **kwargs: {})
    monkeypatch.setattr(harness_runs, "build_invoke_config", lambda **kwargs: {})

    await harness_runs._produce_run_stream(
        runtime=runtime,
        chat=_ProducerChat(final_messages or [AIMessage(content="done")]),
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
    async def fake_stream_graph_chunks(**kwargs):
        del kwargs
        yield {
            "type": "messages",
            "data": (
                SimpleNamespace(content="hello", type="ai", id="msg-1"),
                {"langgraph_node": "agent"},
            ),
            "ns": [],
        }

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
        runtime = SimpleNamespace(
            graph=object(),
            checkpointer=None,
            settings=SimpleNamespace(sse_heartbeat_seconds=0),
            run_manager=manager,
            stream_bridge=bridge,
        )

        monkeypatch.setattr(harness_runs, "stream_graph_chunks", fake_stream_graph_chunks)
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
        assert bridge.events[3][1]["content"] == "done"
        assert bridge.events[4][1]["thread_state"]["thread_id"] == "thread-1"
        assert bridge.events[-1][1]["source_node"] == "harness"
        assert bridge.ended is True
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
            "data": (SimpleNamespace(content="真正回答", type="ai"), {"langgraph_node": "agent"}),
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


def test_produce_run_stream_reports_cancel_as_interrupt(monkeypatch):
    async def fake_stream_graph_chunks(**kwargs):
        del kwargs
        raise asyncio.CancelledError
        yield  # pragma: no cover

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
            graph=object(),
            checkpointer=None,
            settings=SimpleNamespace(sse_heartbeat_seconds=0),
            run_manager=_Manager(),
            stream_bridge=bridge,
        )

        monkeypatch.setattr(harness_runs, "stream_graph_chunks", fake_stream_graph_chunks)
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
        assert event_names[-2:] == ["run.interrupt", "run.closed"]
        assert bridge.events[-2][1]["action"] == "interrupt"

    asyncio.run(scenario())
