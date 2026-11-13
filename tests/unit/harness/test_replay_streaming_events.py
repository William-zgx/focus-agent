import asyncio

from focus_agent.harness import RunStatus
from tests.test_harness_api import _collect_produced_events


def test_custom_memory_namespace_does_not_collide_with_graph_namespace(monkeypatch):
    chunks = [
        {
            "type": "custom",
            "data": {
                "event": "tool",
                "stage": "start",
                "tool_name": "memory_save",
                "namespace": "user/browser-review/profile",
            },
            "ns": ["agent"],
        }
    ]

    async def scenario():
        events, statuses, ended = await _collect_produced_events(monkeypatch, chunks)
        event_names = [event for event, _data in events]
        assert "run.failed" not in event_names

        state_payload = next(
            data
            for event, data in events
            if event == "state.update" and data.get("tool_name") == "memory_save"
        )
        assert state_payload["namespace"] == ["agent"]
        assert state_payload["payload"]["namespace"] == "user/browser-review/profile"
        assert statuses[-1][0] is RunStatus.SUCCESS
        assert ended is True

    asyncio.run(scenario())


def test_custom_tool_payload_preserves_fields_on_publisher_collision(monkeypatch):
    chunks = [
        {
            "type": "custom",
            "data": {
                "event": "tool",
                "stage": "start",
                "tool_call_id": "memory-save-1",
                "tool_name": "memory_save",
                "namespace": "user/browser-review/profile",
                "event_name": "custom-event",
                "source_node_name": "custom-source",
                "payload_namespace": "original-payload-namespace",
                "payload": {"original": True},
            },
            "ns": ["agent"],
        }
    ]

    async def scenario():
        events, statuses, ended = await _collect_produced_events(monkeypatch, chunks)
        event_names = [event for event, _data in events]
        assert "run.failed" not in event_names

        tool_payload = next(data for event, data in events if event == "tool.requested")
        original_payload = tool_payload["payload"]
        assert tool_payload["namespace"] == ["agent"]
        assert original_payload["namespace"] == "user/browser-review/profile"
        assert original_payload["event_name"] == "custom-event"
        assert original_payload["source_node_name"] == "custom-source"
        assert original_payload["payload_namespace"] == "original-payload-namespace"
        assert original_payload["payload"] == {"original": True}
        assert statuses[-1][0] is RunStatus.SUCCESS
        assert ended is True

    asyncio.run(scenario())
