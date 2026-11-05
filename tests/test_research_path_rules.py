"""Unified research-path rules: failure detection, publish dates, continuations."""

from __future__ import annotations

import json

from langchain.messages import AIMessage, HumanMessage, ToolMessage

from focus_agent.engine.graph import web_result_fallback as graph_web_result_fallback
from focus_agent.engine.graph.evidence import normalize_evidence_bundle, normalize_evidence_ledger
from focus_agent.engine.graph.execution_contract import tool_result_names
from focus_agent.engine.graph.tool_history_repair import _has_repeated_failed_tool_call
from focus_agent.engine.graph.tool_messages import (
    artifact_source_refs,
    payload_published_at,
    tool_message_failed,
)


def _fetch_call(*call_ids: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {"id": call_id, "name": "web_fetch", "args": {"url": f"https://{call_id}.example"}}
            for call_id in call_ids
        ],
    )


def _tool(payload: dict, call_id: str, **kwargs) -> ToolMessage:
    return ToolMessage(
        content=json.dumps(payload, ensure_ascii=False), tool_call_id=call_id, **kwargs
    )


def test_tool_message_failed_covers_every_payload_failure_shape() -> None:
    failing = [
        {"status": "error", "error": "blocked"},
        {"status": "failed"},
        {"error": "HTTP 503"},
        {"ok": False},
        {"success": False},
        {"timed_out": True},
        {"exit_code": 2},
        {"stdout": json.dumps({"status": "error"})},
    ]
    for payload in failing:
        assert tool_message_failed(_tool(payload, "x")), payload

    assert tool_message_failed(ToolMessage(content="plain text", tool_call_id="x", status="error"))
    assert not tool_message_failed(ToolMessage(content="plain text", tool_call_id="x"))
    # Provider fallback diagnostics on a successful search are not a failure.
    assert not tool_message_failed(
        _tool({"results": [{"url": "u"}], "errors": [{"provider": "tavily"}]}, "x")
    )


def test_failed_payloads_do_not_satisfy_contract_or_become_evidence() -> None:
    # Previously ok=false / timed_out payloads in success-status messages counted
    # as satisfying web_fetch results and were normalised into evidence.
    messages = [
        _fetch_call("a", "b"),
        _tool({"url": "https://a.example", "ok": False, "content": "x"}, "a"),
        _tool({"url": "https://b.example", "timed_out": True, "content": "y"}, "b"),
    ]

    assert tool_result_names(messages) == []
    assert normalize_evidence_bundle(messages) == []
    assert normalize_evidence_ledger(messages) == []


def test_repeated_failure_detection_sees_status_failed_payloads() -> None:
    # The forced tool-free answer guard used to only recognise status=error, so a
    # tool repeatedly returning status=failed kept looping.
    call = {"name": "web_fetch", "args": {"url": "https://a.example"}}
    messages = [
        HumanMessage(content="q"),
        AIMessage(content="", tool_calls=[{**call, "id": "1"}]),
        _tool({"status": "failed", "error": "HTTP 503"}, "1"),
        AIMessage(content="", tool_calls=[{**call, "id": "2"}]),
        _tool({"status": "failed", "error": "HTTP 503"}, "2"),
    ]

    assert _has_repeated_failed_tool_call(messages, max_repetitions=2)


def test_web_fallback_skips_failed_payloads_reported_with_ok_false() -> None:
    messages = [
        HumanMessage(content="今天北京天气怎么样？"),
        _fetch_call("w"),
        _tool(
            {
                "url": "https://w.example",
                "title": "北京天气",
                "ok": False,
                "content": "今天白天：晴，最高气温28℃；今天夜间：多云，最低气温18℃。",
            },
            "w",
        ),
    ]

    assert graph_web_result_fallback._latest_relevant_web_payloads(messages, "北京天气") == []


def test_publication_date_is_read_from_alternate_and_nested_keys() -> None:
    assert payload_published_at({"published_at": "2026-01-01"}) == "2026-01-01"
    assert payload_published_at({"publishedDate": "2026-01-02"}) == "2026-01-02"
    assert payload_published_at({"metadata": {"published_date": "2026-01-03"}}) == "2026-01-03"
    assert payload_published_at({"meta": {"date": "2026-01-04"}}) == "2026-01-04"
    assert payload_published_at({"title": "none"}) is None

    messages = [
        _fetch_call("n"),
        _tool(
            {
                "url": "https://n.example",
                "content": "Release notes",
                "metadata": {"published_date": "2026-03-02"},
            },
            "n",
        ),
    ]
    [item] = normalize_evidence_bundle(messages)
    assert item["published_at"] == "2026-03-02"


def test_artifact_source_refs_include_observation_and_advertised_refs() -> None:
    refs = artifact_source_refs(
        tool_name="web_fetch",
        tool_call_id="call-1",
        payload={"artifact_ref": "tool-observation://web_fetch/abc"},
        prompt_payload={"artifact_ref": "tool-observation://web_fetch/abc"},
    )

    assert refs == ["tool-observation://web_fetch/call-1", "tool-observation://web_fetch/abc"]
