from __future__ import annotations

import json
import socket
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from focus_agent.capabilities.default_tool_modules.web import build_web_tools
from focus_agent.config import Settings


class _FakeWebHttpClient:
    def __init__(self, get: Callable[..., httpx.Response]) -> None:
        self._get = get

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
        extensions: dict[str, Any] | None = None,
    ) -> httpx.Response:
        return self._get(
            url,
            headers=headers or {},
            timeout=timeout,
            extensions=extensions or {},
        )


def _response(
    url: str,
    body: str = "public",
    *,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return httpx.Response(
        status_code,
        text=body,
        headers=headers,
        request=httpx.Request("GET", url),
    )


def _tool(
    *,
    get: Callable[..., httpx.Response],
) -> Any:
    settings = Settings()
    tools, _ = build_web_tools(
        web_search_config=settings.web_search,
        tool_catalog=settings.tool_catalog,
        resolved_env={},
        emit_tool_event=lambda **_: None,
        http_client=_FakeWebHttpClient(get),
    )
    return tools["web_fetch"]


def _dns_answer(*addresses: str) -> list[tuple[Any, ...]]:
    answers: list[tuple[Any, ...]] = []
    for address in addresses:
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        sockaddr: tuple[Any, ...]
        if family == socket.AF_INET6:
            sockaddr = (address, 0, 0, 0)
        else:
            sockaddr = (address, 0)
        answers.append((family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr))
    return answers


def test_web_fetch_rejects_dns_name_resolving_to_private_address(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _dns_answer("127.0.0.1"),
    )

    def unexpected_get(*_args: Any, **_kwargs: Any) -> httpx.Response:
        raise AssertionError("A private DNS answer must be rejected before connecting.")

    with pytest.raises(ValueError, match="resolved.*non-public|non-public.*resolved"):
        _tool(get=unexpected_get).invoke({"url": "https://rebind.example/data"})


def test_web_fetch_rejects_mixed_public_and_private_dns_answers(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _dns_answer("93.184.216.34", "10.0.0.7"),
    )

    def unexpected_get(*_args: Any, **_kwargs: Any) -> httpx.Response:
        raise AssertionError("Every resolved address must be public.")

    with pytest.raises(ValueError, match="10\\.0\\.0\\.7"):
        _tool(get=unexpected_get).invoke({"url": "https://mixed.example/data"})


def test_web_fetch_tries_only_validated_public_addresses(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _dns_answer("93.184.216.34", "8.8.8.8"),
    )
    seen_urls: list[str] = []

    def fake_get(url, *, headers, timeout, extensions):
        del headers, timeout, extensions
        seen_urls.append(url)
        if url == "https://93.184.216.34/data":
            raise httpx.ConnectError("first address unavailable", request=httpx.Request("GET", url))
        assert url == "https://8.8.8.8/data"
        return _response("https://multi.example/data", "safe")

    payload = json.loads(_tool(get=fake_get).invoke({"url": "https://multi.example/data"}))

    assert seen_urls == ["https://93.184.216.34/data", "https://8.8.8.8/data"]
    assert payload["content"] == "safe"


@pytest.mark.parametrize(
    "address",
    [
        pytest.param("::1", id="ipv6-loopback"),
        pytest.param("fd00::1", id="ipv6-private"),
        pytest.param("fe80::1", id="ipv6-link-local"),
        pytest.param("::", id="ipv6-unspecified"),
        pytest.param("ff02::1", id="ipv6-multicast"),
    ],
)
def test_web_fetch_rejects_non_public_ipv6_answers(monkeypatch, address):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _dns_answer(address),
    )

    def unexpected_get(*_args: Any, **_kwargs: Any) -> httpx.Response:
        raise AssertionError("A non-public IPv6 answer must be rejected before connecting.")

    with pytest.raises(ValueError, match="non-public"):
        _tool(get=unexpected_get).invoke({"url": "https://ipv6.example/data"})


def test_web_fetch_pins_validated_address_and_preserves_https_authority(monkeypatch):
    calls = 0

    def fake_getaddrinfo(*_args: Any, **_kwargs: Any) -> list[tuple[Any, ...]]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return _dns_answer("93.184.216.34")
        return _dns_answer("127.0.0.1")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    def fake_get(url, *, headers, timeout, extensions):
        assert url == "https://93.184.216.34/data"
        assert headers["Host"] == "rebind.example"
        assert extensions["sni_hostname"] == b"rebind.example"
        assert timeout == 30
        return _response("https://rebind.example/data", "safe")

    payload = json.loads(_tool(get=fake_get).invoke({"url": "https://rebind.example/data"}))

    assert calls == 1
    assert payload["final_url"] == "https://rebind.example/data"
    assert payload["content"] == "safe"


def test_web_fetch_preserves_non_default_port_in_host_and_pinned_url(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _dns_answer("93.184.216.34"),
    )

    def fake_get(url, *, headers, timeout, extensions):
        del timeout
        assert url == "https://93.184.216.34:8443/data"
        assert headers["Host"] == "secure.example:8443"
        assert extensions["sni_hostname"] == b"secure.example"
        return _response("https://secure.example:8443/data", "safe")

    payload = json.loads(_tool(get=fake_get).invoke({"url": "https://secure.example:8443/data"}))

    assert payload["final_url"] == "https://secure.example:8443/data"


def test_web_fetch_brackets_public_ipv6_literal_in_host_header():
    address = "2606:2800:220:1:248:1893:25c8:1946"

    def fake_get(url, *, headers, timeout, extensions):
        del timeout
        assert url == f"https://[{address}]/data"
        assert headers["Host"] == f"[{address}]"
        assert extensions["sni_hostname"] == address.encode()
        return _response(f"https://[{address}]/data", "safe")

    payload = json.loads(_tool(get=fake_get).invoke({"url": f"https://[{address}]/data"}))

    assert payload["final_url"] == f"https://[{address}]/data"


def test_web_fetch_resolves_and_pins_every_redirect_hop(monkeypatch):
    answers = {
        "start.example": _dns_answer("93.184.216.34"),
        "next.example": _dns_answer("2606:2800:220:1:248:1893:25c8:1946"),
    }
    resolved: list[str] = []

    def fake_getaddrinfo(host, *_args, **_kwargs):
        resolved.append(host)
        return answers[host]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    seen: list[tuple[str, str, bytes]] = []

    def fake_get(url, *, headers, timeout, extensions):
        del timeout
        seen.append((url, headers["Host"], extensions["sni_hostname"]))
        if url == "https://93.184.216.34/start":
            return _response(
                "https://start.example/start",
                status_code=302,
                headers={"location": "https://next.example/final"},
            )
        assert url == "https://[2606:2800:220:1:248:1893:25c8:1946]/final"
        return _response("https://next.example/final", "redirected")

    payload = json.loads(_tool(get=fake_get).invoke({"url": "https://start.example/start"}))

    assert resolved == ["start.example", "next.example"]
    assert seen == [
        ("https://93.184.216.34/start", "start.example", b"start.example"),
        (
            "https://[2606:2800:220:1:248:1893:25c8:1946]/final",
            "next.example",
            b"next.example",
        ),
    ]
    assert payload["final_url"] == "https://next.example/final"


def test_web_fetch_rejects_redirect_when_any_dns_answer_is_private(monkeypatch):
    answers = {
        "start.example": _dns_answer("93.184.216.34"),
        "redirect.example": _dns_answer("8.8.8.8", "192.168.1.8"),
    }

    monkeypatch.setattr(socket, "getaddrinfo", lambda host, *_args, **_kwargs: answers[host])
    seen_urls: list[str] = []

    def fake_get(url, *, headers, timeout, extensions):
        del headers, timeout, extensions
        seen_urls.append(url)
        return _response(
            "https://start.example/start",
            status_code=302,
            headers={"location": "https://redirect.example/private"},
        )

    with pytest.raises(ValueError, match="redirect.*non-public"):
        _tool(get=fake_get).invoke({"url": "https://start.example/start"})

    assert seen_urls == ["https://93.184.216.34/start"]
