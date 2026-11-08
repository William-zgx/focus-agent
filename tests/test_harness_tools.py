from focus_agent.harness.tools import tool_schema_fingerprint, tools_schema_fingerprint


class DummyTool:
    def __init__(self, *, description: str, args: dict[str, object]) -> None:
        self.name = "lookup"
        self.description = description
        self.args = args


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
