from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx

from .web_helpers import (
    _ddgs_time_range,
    _is_timeout_exception,
    _normalize_search_result,
    _WebSearchProviderError,
)


def _make_provider_error(
    *,
    provider: str,
    category: str,
    message: str,
    retryable: bool = False,
    status_code: int | None = None,
    attempt: int | None = None,
    errors: list[dict[str, Any]] | None = None,
) -> _WebSearchProviderError:
    return _WebSearchProviderError(
        provider=provider,
        category=category,
        message=message,
        retryable=retryable,
        status_code=status_code,
        attempt=attempt,
        errors=errors,
    )


def _tavily_status_error(exc: Exception) -> _WebSearchProviderError | None:
    if not isinstance(exc, httpx.HTTPStatusError):
        return None
    status_code = int(exc.response.status_code)
    body = exc.response.text
    if status_code == 429:
        category = "rate_limited"
        retryable = True
    elif status_code == 408:
        category = "timeout"
        retryable = False
    elif 500 <= status_code < 600:
        category = "provider_error"
        retryable = True
    else:
        category = "provider_error"
        retryable = False
    return _make_provider_error(
        provider="tavily",
        category=category,
        message=f"Tavily search failed with HTTP {status_code}: {body[:300]}",
        retryable=retryable,
        status_code=status_code,
    )


def _tavily_post_raw(
    payload: dict[str, Any],
    *,
    attempt: int,
    http: Callable[[], httpx.Client],
    tavily_api_key: str,
) -> str:
    response = http().post(
        "https://api.tavily.com/search",
        json=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {tavily_api_key}",
        },
        timeout=30,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status_error = _tavily_status_error(exc)
        if status_error is not None:
            status_error.attempt = attempt
            raise status_error from exc
        raise
    return response.text


def _run_tavily_search(
    *,
    http: Callable[[], httpx.Client],
    tavily_api_key: str,
    query: str,
    max_results: int,
    attempt: int,
    time_range: str | None,
    include_domains: list[str],
    exclude_domains: list[str],
) -> dict[str, Any]:
    if not tavily_api_key:
        raise _make_provider_error(
            provider="tavily",
            category="missing_api_key",
            message="TAVILY_API_KEY is not configured.",
            attempt=attempt,
        )
    payload = {
        "query": query,
        "max_results": max_results,
        "include_answer": True,
    }
    if time_range is not None:
        payload["time_range"] = time_range
    if include_domains:
        payload["include_domains"] = include_domains
    if exclude_domains:
        payload["exclude_domains"] = exclude_domains
    try:
        raw = _tavily_post_raw(
            payload,
            attempt=attempt,
            http=http,
            tavily_api_key=tavily_api_key,
        )
    except _WebSearchProviderError:
        raise
    except httpx.TimeoutException as exc:
        raise _make_provider_error(
            provider="tavily",
            category="timeout",
            message=f"Tavily search failed: {exc}",
            retryable=True,
            attempt=attempt,
        ) from exc
    except httpx.HTTPError as exc:
        raise _make_provider_error(
            provider="tavily",
            category="provider_error",
            message=f"Tavily search failed: {exc}",
            retryable=True,
            attempt=attempt,
        ) from exc
    except OSError as exc:
        category = "timeout" if _is_timeout_exception(exc) else "provider_error"
        raise _make_provider_error(
            provider="tavily",
            category=category,
            message=f"Tavily search failed: {exc}",
            retryable=True,
            attempt=attempt,
        ) from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _make_provider_error(
            provider="tavily",
            category="invalid_payload",
            message="Tavily search returned invalid JSON.",
            attempt=attempt,
        ) from exc

    if not isinstance(data, dict):
        raise _make_provider_error(
            provider="tavily",
            category="invalid_payload",
            message="Tavily search returned an unusable payload.",
            attempt=attempt,
        )
    results = data.get("results")
    if not isinstance(results, list):
        raise _make_provider_error(
            provider="tavily",
            category="invalid_payload",
            message="Tavily search returned an unusable payload.",
            attempt=attempt,
        )

    normalized_results: list[dict[str, Any]] = []
    for item in results[:max_results]:
        if not isinstance(item, dict):
            raise _make_provider_error(
                provider="tavily",
                category="invalid_payload",
                message="Tavily search returned an unusable result item.",
                attempt=attempt,
            )
        normalized_results.append(
            _normalize_search_result(
                title=item.get("title"),
                url=item.get("url"),
                content=item.get("content"),
                metadata=item,
            )
        )
    if not normalized_results:
        raise _make_provider_error(
            provider="tavily",
            category="empty_results",
            message="Tavily search returned no results.",
            attempt=attempt,
        )

    return {
        "query": query,
        "provider": "tavily",
        "answer": data.get("answer"),
        "results": normalized_results,
        "search_filters": {
            "time_range": time_range,
            "include_domains": list(include_domains),
            "exclude_domains": list(exclude_domains),
            "domain_filter_mode": "native",
        },
    }


def _run_duckduckgo_search(
    *,
    query: str,
    max_results: int,
    attempt: int,
    time_range: str | None,
    include_domains: list[str],
    exclude_domains: list[str],
) -> dict[str, Any]:
    try:
        from ddgs import DDGS
    except ImportError as exc:
        raise _make_provider_error(
            provider="duckduckgo",
            category="provider_error",
            message="DuckDuckGo fallback is unavailable because 'ddgs' is not installed.",
            attempt=attempt,
        ) from exc

    ddgs_query = query
    if include_domains:
        include_query = " OR ".join(
            f"site:{domain.removeprefix('*.')}" for domain in include_domains
        )
        ddgs_query = f"({ddgs_query}) ({include_query})"
    if exclude_domains:
        ddgs_query = " ".join(
            [ddgs_query, *(f"-site:{domain.removeprefix('*.')}" for domain in exclude_domains)]
        )

    ddgs_kwargs: dict[str, Any] = {
        "region": "wt-wt",
        "safesearch": "moderate",
        "max_results": max_results,
    }
    ddgs_time_range = _ddgs_time_range(time_range)
    if ddgs_time_range is not None:
        ddgs_kwargs["timelimit"] = ddgs_time_range
    try:
        with DDGS(timeout=30) as ddgs:
            raw_results = list(
                ddgs.text(
                    ddgs_query,
                    **ddgs_kwargs,
                )
                or []
            )
    except Exception as exc:  # noqa: BLE001
        category = "timeout" if _is_timeout_exception(exc) else "provider_error"
        message = str(exc).lower()
        if "429" in message or "rate limit" in message or "rate_limited" in message:
            category = "rate_limited"
        raise _make_provider_error(
            provider="duckduckgo",
            category=category,
            message=f"DuckDuckGo search failed: {exc}",
            attempt=attempt,
        ) from exc

    normalized_results: list[dict[str, Any]] = []
    for item in raw_results[:max_results]:
        if not isinstance(item, dict):
            raise _make_provider_error(
                provider="duckduckgo",
                category="invalid_payload",
                message="DuckDuckGo search returned an unusable result item.",
                attempt=attempt,
            )
        normalized_results.append(
            _normalize_search_result(
                title=item.get("title"),
                url=item.get("href") or item.get("link"),
                content=item.get("body") or item.get("snippet"),
                metadata=item,
            )
        )
    if not normalized_results:
        raise _make_provider_error(
            provider="duckduckgo",
            category="empty_results",
            message="DuckDuckGo search returned no results.",
            attempt=attempt,
        )

    return {
        "query": query,
        "provider": "duckduckgo",
        "answer": None,
        "results": normalized_results,
        "search_filters": {
            "time_range": time_range,
            "include_domains": list(include_domains),
            "exclude_domains": list(exclude_domains),
            "provider_query": ddgs_query,
            "domain_filter_mode": "query_operators",
        },
    }
