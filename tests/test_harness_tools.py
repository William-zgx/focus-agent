from langchain.messages import ToolMessage

from focus_agent.harness.tools import (
    ToolResultEnvelope,
    envelope_to_tool_message,
    tool_message_to_envelope,
    tool_schema_fingerprint,
    tools_schema_fingerprint,
)


class DummyTool:
    def __init__(self, *, description: str, args: dict[str, object]) -> None:
        self.name = "lookup"
        self.description = description
        self.args = args


def test_tool_result_envelope_round_trips_langchain_tool_message():
    message = ToolMessage(
        content='{"answer":"42"}',
        tool_call_id="call-1",
        name="lookup",
        status="success",
        artifact={
            "runtime": {"duration_ms": 12, "cache_hit": False},
            "tool_name": "lookup",
            "prompt_observation": "lookup returned one result",
            "artifact_ref": "artifact://one",
        },
    )

    envelope = tool_message_to_envelope(message)
    assert envelope == ToolResultEnvelope(
        tool_call_id="call-1",
        tool_name="lookup",
        content='{"answer":"42"}',
        status="success",
        runtime={"duration_ms": 12, "cache_hit": False},
        prompt_observation="lookup returned one result",
        artifact={"artifact_ref": "artifact://one"},
        name="lookup",
    )

    restored = envelope_to_tool_message(envelope)
    assert restored.tool_call_id == "call-1"
    assert restored.status == "success"
    assert restored.artifact["runtime"]["duration_ms"] == 12
    assert restored.artifact["tool_name"] == "lookup"


def test_tool_schema_fingerprint_changes_when_schema_or_description_changes():
    base = DummyTool(description="Lookup records", args={"query": {"type": "string"}})
    changed_description = DummyTool(
        description="Lookup records with recency",
        args={"query": {"type": "string"}},
    )
    changed_schema = DummyTool(
        description="Lookup records",
        args={"query": {"type": "string"}, "limit": {"type": "integer"}},
    )

    assert tool_schema_fingerprint(base) != tool_schema_fingerprint(changed_description)
    assert tool_schema_fingerprint(base) != tool_schema_fingerprint(changed_schema)


def test_tools_schema_fingerprint_is_order_stable():
    first = DummyTool(description="Lookup records", args={"query": {"type": "string"}})
    second = DummyTool(description="Fetch records", args={"url": {"type": "string"}})
    second.name = "fetch"

    assert tools_schema_fingerprint([first, second]) == tools_schema_fingerprint([second, first])
