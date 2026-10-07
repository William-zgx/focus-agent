from __future__ import annotations

import json
import sys
import types
from dataclasses import asdict
from typing import Any

import httpx
import pytest

from focus_agent.capabilities.default_tool_modules.web import build_web_tools
from focus_agent.config import Settings


class _SearchClient:
    def __init__(self, body: dict[str, Any]):
        self.body = body
        self.payloads: list[dict[str, Any]] = []

    def post(self, url: str, *, json: dict[str, Any], headers, timeout) -> httpx.Response:
        del headers, timeout
        self.payloads.append(json)
        return httpx.Response(
            200,
            json=self.body,
            request=httpx.Request("POST", url),
        )


class _FetchClient:
    def __init__(self, response: httpx.Response):
        self.response = response

    def get(self, url: str, *, headers, timeout, extensions) -> httpx.Response:
        del headers, timeout, extensions
        self.response.request = httpx.Request("GET", url)
        return self.response


def _build_search_tools(*, provider: str, client: Any, env: dict[str, str] | None = None):
    settings = Settings()
    config = types.SimpleNamespace(
        **{
            **asdict(settings.web_search),
            "provider": provider,
            "fallback_provider": None,
        }
    )
    tools, _ = build_web_tools(
        web_search_config=config,
        tool_catalog=settings.tool_catalog,
        resolved_env=env or {"TAVILY_API_KEY": "test-key"},
        emit_tool_event=lambda **_: None,
        http_client=client,
    )
    return tools


def test_tavily_search_sends_filters_and_preserves_source_metadata():
    client = _SearchClient(
        {
            "answer": "answer",
            "results": [
                {
                    "title": "Result",
                    "url": "https://example.com/article",
                    "content": "snippet",
                    "published_date": "2026-10-01",
                    "score": 0.91,
                    "source": "example.com",
                }
            ],
        }
    )
    tools = _build_search_tools(provider="tavily", client=client)

    payload = json.loads(
        tools["web_search"].invoke(
            {
                "query": "recent news",
                "max_results": 3,
                "time_range": "week",
                "include_domains": ["Example.com"],
                "exclude_domains": ["spam.example"],
            }
        )
    )

    assert client.payloads == [
        {
            "query": "recent news",
            "max_results": 3,
            "include_answer": True,
            "time_range": "week",
            "include_domains": ["example.com"],
            "exclude_domains": ["spam.example"],
        }
    ]
    assert payload["time_range"] == "week"
    assert payload["results"][0]["published_date"] == "2026-10-01"
    assert payload["results"][0]["score"] == 0.91
    assert payload["results"][0]["source"] == "example.com"


def test_duckduckgo_applies_time_and_domain_filters_explicitly(monkeypatch):
    calls: list[tuple[str, dict[str, Any]]] = []

    class FakeDDGS:
        def __init__(self, *, timeout: int):
            assert timeout == 30

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def text(self, query: str, **kwargs: Any):
            calls.append((query, kwargs))
            return [
                {
                    "title": "Result",
                    "href": "https://example.com/article",
                    "body": "snippet",
                    "date": "2026-10-02",
                }
            ]

    monkeypatch.setitem(sys.modules, "ddgs", types.SimpleNamespace(DDGS=FakeDDGS))
    payload = json.loads(
        _build_search_tools(provider="duckduckgo", client=object())["web_search"].invoke(
            {
                "query": "recent news",
                "time_range": "day",
                "include_domains": ["example.com", "news.example"],
                "exclude_domains": ["spam.example"],
            }
        )
    )

    assert calls == [
        (
            "(recent news) (site:example.com OR site:news.example) -site:spam.example",
            {
                "region": "wt-wt",
                "safesearch": "moderate",
                "max_results": 5,
                "timelimit": "d",
            },
        )
    ]
    assert payload["search_filters"]["time_range"] == "day"
    assert payload["results"][0]["published_date"] == "2026-10-02"


def test_invalid_time_range_is_rejected_instead_of_ignored():
    tools = _build_search_tools(provider="duckduckgo", client=object())
    with pytest.raises(ValueError, match="time_range"):
        tools["web_search"].invoke({"query": "news", "time_range": "quarter"})


def test_web_fetch_downloads_before_display_truncation_and_returns_scoped_continuation():
    body = (
        "<html><body><main><p>See <a href='/source'>source</a>.</p>"
        + ("word " * 5000)
        + "</main></body></html>"
    )
    response = httpx.Response(
        200,
        content=body.encode(),
        headers={"content-type": "text/html; charset=utf-8"},
    )
    settings = Settings()
    saved: list[dict[str, Any]] = []
    tools, _ = build_web_tools(
        web_search_config=settings.web_search,
        tool_catalog=settings.tool_catalog,
        resolved_env={},
        emit_tool_event=lambda **_: None,
        http_client=_FetchClient(response),
        save_tool_observation=lambda **kwargs: saved.append(kwargs) or "saved",
        get_current_thread_id=lambda: "thread-1",
    )

    payload = json.loads(
        tools["web_fetch"].invoke({"url": "https://93.184.216.34/article", "max_chars": 120})
    )

    assert payload["truncated"] is True
    assert payload["fetch_limited"] is False
    assert payload["content_chars"] > 80
    assert "[source](https://93.184.216.34/source)" in payload["content"]
    assert payload["artifact_ref"].startswith("tool-observation://web_fetch/")
    assert payload["next_offset"] > 0
    assert saved[0]["thread_id"] == "thread-1"
    assert len(saved[0]["content"]) == payload["content_chars"]
    for limit in (1, 2, 27, 28, 29, 30):
        preview = json.loads(
            tools["web_fetch"].invoke({"url": "https://93.184.216.34/article", "max_chars": limit})
        )
        assert len(preview["content"]) <= limit
        assert preview["next_offset"] > 0


def test_web_fetch_does_not_render_pdf_as_replacement_text():
    response = httpx.Response(
        200,
        content=b"%PDF-1.7\x00garbled binary",
        headers={"content-type": "application/pdf"},
    )
    settings = Settings()
    tools, _ = build_web_tools(
        web_search_config=settings.web_search,
        tool_catalog=settings.tool_catalog,
        resolved_env={},
        emit_tool_event=lambda **_: None,
        http_client=_FetchClient(response),
    )

    payload = json.loads(tools["web_fetch"].invoke({"url": "https://93.184.216.34/paper.pdf"}))

    assert payload["binary"] is True
    assert payload["content"] == ""
    assert "PDF" in payload["error"]


def test_default_web_fetch_continuation_reads_full_text_in_same_thread(tmp_path, monkeypatch):
    from focus_agent.capabilities.default_tool_modules import factory
    from focus_agent.capabilities.default_tool_modules import web as web_module

    active_thread = ["research-thread"]
    monkeypatch.setattr(factory, "_get_current_thread_id", lambda: active_thread[0])
    content = "opening\n" + "middle evidence\n" * 500 + "conclusion"
    response = httpx.Response(
        200,
        text=content,
        headers={"content-type": "text/plain"},
        request=httpx.Request("GET", "https://93.184.216.34/page"),
    )
    monkeypatch.setattr(web_module, "request_pinned_fetch_url", lambda **_: response)
    settings = Settings(workspace_root=str(tmp_path), artifact_dir=str(tmp_path / "artifacts"))
    tools = {t.name: t for t in factory.get_default_tools(settings)}
    page = json.loads(
        tools["web_fetch"].invoke({"url": "https://93.184.216.34/page", "max_chars": 120})
    )
    continuation = page["continuation"]
    read = json.loads(tools[continuation["tool"]].invoke(continuation["args"]))
    offset = continuation["args"]["offset"]
    assert read["content"] == content[offset : offset + 120]
    assert read["total_chars"] == len(content)
    reference = page["artifact_ref"]
    hit = json.loads(
        tools["artifact_read"].invoke(
            {
                "artifact_id": reference,
                "query": "CONCLUSION",
                "limit": 100,
            }
        )
    )
    assert hit["found"] is True
    assert hit["offset"] == content.index("conclusion")
    assert hit["content"] == "conclusion"
    first = json.loads(
        tools["artifact_read"].invoke(
            {
                "artifact_id": reference,
                "query": "evidence",
                "limit": 8,
            }
        )
    )
    second = json.loads(
        tools["artifact_read"].invoke(
            {
                "artifact_id": reference,
                "query": "evidence",
                "offset": first["next_offset"],
                "limit": 8,
            }
        )
    )
    assert second["offset"] > first["offset"]
    missing = json.loads(
        tools["artifact_read"].invoke(
            {
                "artifact_id": reference,
                "query": "middle.evidence",
            }
        )
    )
    assert missing["found"] is False
    assert missing["content"] == ""
    assert missing["next_offset"] is None
    active_thread[0] = "other-thread"
    with pytest.raises((PermissionError, FileNotFoundError)):
        tools["artifact_read"].invoke(continuation["args"])


def test_web_fetch_preserves_publication_date_and_rejects_challenge_pages():
    html = '<html><head><meta property="article:published_time" content="2025-01-01"></head><body><article><h1>Release</h1><p>Details</p></article></body></html>'
    settings = Settings()
    response = httpx.Response(200, text=html, headers={"content-type": "text/html"})
    tools, _ = build_web_tools(
        web_search_config=settings.web_search,
        tool_catalog=settings.tool_catalog,
        resolved_env={},
        emit_tool_event=lambda **_: None,
        http_client=_FetchClient(response),
    )
    result = json.loads(tools["web_fetch"].invoke({"url": "https://93.184.216.34/old"}))
    assert result["published_at"] == "2025-01-01"
    assert result["observed_at"] != result["published_at"]
    assert result["content"] == "# Release\nDetails"
    tiny = json.loads(
        tools["web_fetch"].invoke({"url": "https://93.184.216.34/old", "max_chars": 2})
    )
    assert len(tiny["content"]) == 2
    response = httpx.Response(
        200,
        text="<html><title>Just a moment...</title><body>Checking your browser</body></html>",
        headers={"content-type": "text/html"},
    )
    tools, _ = build_web_tools(
        web_search_config=settings.web_search,
        tool_catalog=settings.tool_catalog,
        resolved_env={},
        emit_tool_event=lambda **_: None,
        http_client=_FetchClient(response),
    )
    blocked = json.loads(tools["web_fetch"].invoke({"url": "https://93.184.216.34/blocked"}))
    assert blocked["status"] == "error"
    assert not blocked["content"]


def test_web_fetch_prefers_role_main_over_navigation_text():
    html = (
        "<html><body><header>Navigation noise</header>"
        '<div class="body" role="main"><h1>Primary heading</h1>'
        "<p>Primary page content.</p></div><footer>Footer noise</footer></body></html>"
    )
    settings = Settings()
    response = httpx.Response(200, text=html, headers={"content-type": "text/html"})
    tools, _ = build_web_tools(
        web_search_config=settings.web_search,
        tool_catalog=settings.tool_catalog,
        resolved_env={},
        emit_tool_event=lambda **_: None,
        http_client=_FetchClient(response),
    )

    result = json.loads(tools["web_fetch"].invoke({"url": "https://93.184.216.34/main"}))

    assert result["content"] == "# Primary heading\nPrimary page content."


def test_fetch_transport_stops_stream_after_decoded_byte_limit():
    from focus_agent.capabilities.default_tool_modules.web_transport import _bounded_fetch

    class Body(httpx.SyncByteStream):
        consumed = 0
        closed = False

        def __iter__(self):
            for _ in range(20):
                self.consumed += 1
                yield b"x" * 65536

        def close(self):
            self.closed = True

    body = Body()
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=body))
    ) as client:
        response = _bounded_fetch(client, "https://example.com", max_bytes=100000)
    assert len(response.content) == 100001
    assert body.consumed == 2
    assert body.closed


def _extract(html: str) -> str:
    from focus_agent.capabilities.default_tool_modules.web_helpers import (
        _ReadableHTMLExtractor,
    )

    parser = _ReadableHTMLExtractor(base_url="https://example.com/")
    parser.feed(html)
    parser.close()
    return parser.text


def test_html_extractor_keeps_text_after_unclosed_link():
    unclosed = _extract("<main><p>Intro <a href='/x'>link<p>Para two body</main>")
    assert "Para two body" in unclosed
    assert "https://example.com/x" in unclosed

    closed_by_parent = _extract("<main><p>A <a href='/x'>link</p><p>B para</p></main>")
    assert closed_by_parent == "A [link](https://example.com/x)\nB para"


def test_html_extractor_falls_back_when_main_root_is_empty():
    assert _extract("<div role=main><div></div></div><div><p>Real body</p></div>") == "Real body"


def test_default_web_fetch_fits_observation_cap_without_skipping_text():
    from focus_agent.capabilities.default_tool_modules.web import (
        _WEB_FETCH_MAX_OBSERVATION_CHARS,
    )

    body = "".join(f"<p>Paragraph {index} with \"quoted\" evidence.</p>" for index in range(400))
    response = httpx.Response(
        200,
        content=f"<html><body><main>{body}</main></body></html>".encode(),
        headers={"content-type": "text/html; charset=utf-8"},
    )
    settings = Settings()
    saved: list[dict[str, Any]] = []
    tools, _ = build_web_tools(
        web_search_config=settings.web_search,
        tool_catalog=settings.tool_catalog,
        resolved_env={},
        emit_tool_event=lambda **_: None,
        http_client=_FetchClient(response),
        save_tool_observation=lambda **kwargs: saved.append(kwargs) or "saved",
        get_current_thread_id=lambda: "thread-1",
    )

    result = tools["web_fetch"].invoke({"url": "https://93.184.216.34/long"})
    payload = json.loads(result)

    # Over the cap, the observation would be trimmed again after the tool returns,
    # hiding text between the shown head and the continuation offset.
    assert len(result) <= _WEB_FETCH_MAX_OBSERVATION_CHARS
    assert len(saved) == 1
    full_text = saved[0]["content"]
    next_offset = payload["next_offset"]
    assert payload["content"].startswith(full_text[:next_offset])
    assert payload["continuation"]["args"]["offset"] == next_offset
