from langchain.messages import AIMessage, HumanMessage, ToolMessage

from focus_agent.engine.graph.retrieval_ledger import (
    collect_retrieval_ledger,
    retrieval_key,
    retrieval_ledger_note,
)


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
    note = retrieval_ledger_note(ledger)
    assert 'web_search "agent news"' in note
    assert "stale" not in note
    assert retrieval_ledger_note({}) == ""


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
    assert "failed permanently" in retrieval_ledger_note(ledger)


def test_ledger_labels_fetched_pages_and_their_continuations_with_dates():
    page = (
        '{"url": "https://blog.example/agents-week", "published_at": "2026-04-20T09:00:00Z", '
        '"artifact_ref": "tool-observation://web_fetch/abc", "content": "Agents week"}'
    )
    messages = [
        HumanMessage(content="最近两个月Agent领域的进展"),
        _call("fetch", "web_fetch", {"url": "https://blog.example/agents-week"}),
        ToolMessage(content=page, tool_call_id="fetch"),
        _call(
            "read",
            "artifact_read",
            {"artifact_id": "tool-observation://web_fetch/abc", "offset": 4000},
        ),
        ToolMessage(content='{"content": "more"}', tool_call_id="read"),
    ]

    note = retrieval_ledger_note(collect_retrieval_ledger(messages))

    assert "web_fetch https://blog.example/agents-week [published 2026-04-20]" in note
    assert "offset=4000 [page published 2026-04-20]" in note
    assert "outside the requested time window" in note
