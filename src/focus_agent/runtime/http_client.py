from __future__ import annotations

import httpx

_async_client: httpx.AsyncClient | None = None
_sync_client: httpx.Client | None = None


def shared_async_http_client() -> httpx.AsyncClient:
    global _async_client
    if _async_client is None:
        _async_client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=5.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            headers={"User-Agent": "focus-agent/1.0"},
        )
    return _async_client


def shared_sync_http_client() -> httpx.Client:
    global _sync_client
    if _sync_client is None:
        _sync_client = httpx.Client(
            timeout=httpx.Timeout(30.0, connect=5.0),
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
            headers={"User-Agent": "focus-agent/1.0"},
        )
    return _sync_client


async def aclose() -> None:
    global _async_client
    if _async_client is not None:
        await _async_client.aclose()
        _async_client = None


def close() -> None:
    global _sync_client
    if _sync_client is not None:
        _sync_client.close()
        _sync_client = None


__all__ = ["aclose", "close", "shared_async_http_client", "shared_sync_http_client"]
