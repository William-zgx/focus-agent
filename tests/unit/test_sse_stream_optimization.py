from __future__ import annotations

import pytest
from starlette.requests import Request

from focus_agent.api.streaming.sse import build_stream_proxy, should_optimize_for_request


def _request(*, query: str = "", headers: dict[str, str] | None = None) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "query_string": query.encode(),
            "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        }
    )


@pytest.mark.parametrize(
    ("query", "headers"),
    [
        ("optimize_stream=true", {}),
        ("optimize_stream=ON", {}),
        ("", {"X-Stream-Optimize": " yes "}),
        ("", {"Accept": "text/event-stream; stream-optimized"}),
        ("", {"X-Stream-Optimize-Auto": "1", "User-Agent": "Mozilla/5.0"}),
    ],
)
def test_stream_optimization_opt_in(query: str, headers: dict[str, str]) -> None:
    request = _request(query=query, headers=headers)
    assert should_optimize_for_request(request) is True
    assert build_stream_proxy(request) is not None


@pytest.mark.parametrize(
    ("query", "headers"),
    [
        ("", {}),
        ("optimize_stream=false", {}),
        ("", {"X-Stream-Optimize": "0"}),
        ("", {"X-Stream-Optimize-Auto": "1", "User-Agent": "curl/8.0"}),
    ],
)
def test_stream_optimization_defaults_off(query: str, headers: dict[str, str]) -> None:
    request = _request(query=query, headers=headers)
    assert should_optimize_for_request(request) is False
    assert build_stream_proxy(request) is None
