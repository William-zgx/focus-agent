import asyncio
from types import SimpleNamespace

from langchain.messages import AIMessageChunk

from focus_agent.harness.agents.facade import FocusAgent


class _RecordingBridge:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []
        self.ended_runs: list[str] = []

    async def publish(self, _run_id: str, event: str, data: dict):
        self.events.append((event, data))

    async def publish_end(self, run_id: str):
        self.ended_runs.append(run_id)


class _StreamingHarness:
    def __init__(self, chunks, bridge):
        self._chunks = chunks
        self.stream_bridge = bridge

    async def stream_chunks(self, **_kwargs):
        for chunk in self._chunks:
            yield chunk


def _message_chunk(content, *, stream_phase: str):
    return {
        "type": "messages",
        "data": (
            SimpleNamespace(content=content, type="ai"),
            {"langgraph_node": "agent_loop", "stream_phase": stream_phase},
        ),
        "ns": [],
    }


def test_focus_agent_facade_uses_canonical_stream_visibility_gate():
    tool_chunk = AIMessageChunk(
        content="",
        tool_call_chunks=[
            {
                "id": "call-1",
                "name": "web_search",
                "args": '{"query":"Moonshot AI"}',
            }
        ],
    )
    chunks = [
        _message_chunk("隔离草稿", stream_phase="quarantine"),
        _message_chunk(
            [{"type": "reasoning_delta", "text": "先检查可用来源。"}],
            stream_phase="visible",
        ),
        {
            "type": "messages",
            "data": (
                tool_chunk,
                {"langgraph_node": "agent_loop", "stream_phase": "visible"},
            ),
            "ns": [],
        },
        _message_chunk("最终用户可见答复。", stream_phase="visible"),
    ]

    async def scenario():
        bridge = _RecordingBridge()
        agent = FocusAgent(_StreamingHarness(chunks, bridge))

        result = await agent._run_stream_graph(
            run_id="run-1",
            thread_id="thread-1",
            payload={"messages": []},
            config={},
            context=SimpleNamespace(),
            settings=SimpleNamespace(),
        )

        event_names = [event for event, _data in bridge.events]
        message_deltas = [
            data["delta"] for event, data in bridge.events if event == "message.delta"
        ]
        reasoning_deltas = [
            data["delta"] for event, data in bridge.events if event == "reasoning.delta"
        ]

        assert result.status == "success"
        assert result.visible_text == "最终用户可见答复。"
        assert message_deltas == ["最终用户可见答复。"]
        assert reasoning_deltas == ["先检查可用来源。"]
        assert "tool.requested" in event_names
        assert "tool.call.delta" in event_names
        assert bridge.ended_runs == ["run-1"]

    asyncio.run(scenario())
