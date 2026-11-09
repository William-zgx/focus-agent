from langchain.messages import AIMessage, HumanMessage, ToolMessage

from focus_agent.engine.tools.retrieval_ledger import collect_retrieval_ledger, retrieval_key


def _call(call_id: str, name: str, args: dict) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"id": call_id, "name": name, "args": args}])


def test_retrieval_key_normalizes_equivalent_calls():
    assert retrieval_key("web_search", {"query": "  Agent   NEWS "}) == retrieval_key(
        "web_search", {"query": "agent news", "max_results": 8}
    )
    assert retrieval_key("web_search", {"query": "agent news"}) != retrieval_key(
        "web_search", {"query": "agent news", "time_range": "week"}
    )
    assert retrieval_key("web_fetch", {"url": "https://Example.com/a/#top"}) == retrieval_key(
        "web_fetch", {"url": "https://example.com/a"}
    )
    assert retrieval_key("artifact_read", {"artifact_id": "x", "offset": 0}) != retrieval_key(
        "artifact_read", {"artifact_id": "x", "offset": 4000}
    )
    assert retrieval_key("current_utc_time", {}) is None


def test_ledger_tracks_only_successful_retrieval_in_latest_turn():
    messages = [
        HumanMessage(content="old question"),
        _call("old", "web_search", {"query": "stale"}),
        ToolMessage(content="{}", tool_call_id="old"),
        HumanMessage(content="new question"),
        _call("ok", "web_search", {"query": "agent news"}),
        ToolMessage(content='{"results": []}', tool_call_id="ok"),
        _call("failed", "web_fetch", {"url": "https://example.com/a"}),
        ToolMessage(content="timeout", tool_call_id="failed", status="error"),
    ]

    ledger = collect_retrieval_ledger(messages)

    assert list(ledger) == [retrieval_key("web_search", {"query": "agent news"})]


def test_ledger_remembers_permanent_fetch_failures_but_not_transient_ones():
    forbidden_url = {"url": "https://openai.com/index/post/"}
    messages = [
        HumanMessage(content="question"),
        _call("forbidden", "web_fetch", forbidden_url),
        ToolMessage(
            content="Client error '403 Forbidden' for url",
            tool_call_id="forbidden",
            status="error",
        ),
        _call("timeout", "web_fetch", {"url": "https://example.com/slow"}),
        ToolMessage(content="Read timed out", tool_call_id="timeout", status="error"),
    ]

    ledger = collect_retrieval_ledger(messages)

    entry = ledger[retrieval_key("web_fetch", {"url": "https://openai.com/index/post"})]
    assert "403" in entry.error
    assert retrieval_key("web_fetch", {"url": "https://example.com/slow"}) not in ledger


def test_ledger_treats_error_payloads_as_failures_not_successful_retrievals():
    # web_fetch reports failures as JSON payloads inside a success-status
    # ToolMessage; those must not block a retry of a transiently failing page.
    messages = [
        HumanMessage(content="question"),
        _call("busy", "web_fetch", {"url": "https://d.example/slow"}),
        ToolMessage(
            content='{"url": "https://d.example/slow", "status": "failed", "error": "HTTP 503"}',
            tool_call_id="busy",
        ),
    ]

    assert collect_retrieval_ledger(messages) == {}
