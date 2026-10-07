from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib import parse as stdlib_urllib_parse

import httpx
from langchain.tools import tool

from focus_agent.runtime.http_client import shared_sync_http_client

from .common import _require_non_empty_text_arg
from .web_helpers import (
    _TAVILY_MAX_ATTEMPTS,
    _binary_payload_kind,
    _ddgs_time_range,
    _head_tail_text_window,
    _is_timeout_exception,
    _normalize_search_domains,
    _normalize_search_result,
    _normalize_search_time_range,
    _provider_error_record,
    _ReadableHTMLExtractor,
    _resolve_public_fetch_addresses,
    _web_fetch_policy_violation,
    _WebSearchProviderError,
)
from .web_transport import request_pinned_fetch_url

_WEB_FETCH_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_WEB_FETCH_MAX_REDIRECTS = 5
_WEB_FETCH_MAX_BYTES = 8 * 1024 * 1024
_WEB_FETCH_TRUNCATION_MARKER = "\n\n[... middle omitted ...]\n\n"
_TAVILY_MAX_QUERY_CHARS = 400


def _normalize_web_search_query(query: str) -> tuple[str, bool]:
    normalized = " ".join(str(query or "").split())
    if len(normalized) <= _TAVILY_MAX_QUERY_CHARS:
        return normalized, False
    truncated = normalized[:_TAVILY_MAX_QUERY_CHARS].rstrip()
    return truncated, True


def build_web_tools(
    *,
    web_search_config: Any,
    tool_catalog: Any,
    resolved_env: Any,
    emit_tool_event: Callable[..., None],
    urllib_parse_module: Any = stdlib_urllib_parse,
    http_client: httpx.Client | None = None,
    save_tool_observation: Callable[..., str | None] | None = None,
    get_current_thread_id: Callable[[], str | None] | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    def _validate_web_fetch_args(args: dict[str, Any]) -> None:
        _require_non_empty_text_arg(args, "url")

    def _validate_web_search_args(args: dict[str, Any]) -> None:
        _require_non_empty_text_arg(args, "query")

    def _validate_search_filters(
        *,
        time_range: Any = None,
        include_domains: Any = None,
        exclude_domains: Any = None,
    ) -> tuple[str | None, list[str], list[str]]:
        normalized_time_range = _normalize_search_time_range(time_range)
        normalized_include_domains = _normalize_search_domains(
            include_domains, field_name="include_domains"
        )
        normalized_exclude_domains = _normalize_search_domains(
            exclude_domains, field_name="exclude_domains"
        )
        return (
            normalized_time_range,
            normalized_include_domains,
            normalized_exclude_domains,
        )

    preferred_web_search_provider = (
        str(web_search_config.provider or "auto").strip().lower() or "auto"
    )
    fallback_web_search_provider = (
        str(web_search_config.fallback_provider).strip().lower()
        if web_search_config.fallback_provider
        else None
    )
    tavily_api_key = (
        resolved_env.get(web_search_config.api_key_env, "").strip()
        if web_search_config.api_key_env
        else ""
    ) or str(web_search_config.api_key_default or "").strip()
    blocked_fetch_domains = tuple(getattr(tool_catalog.web_fetch, "blocked_domains", ()) or ())
    allowed_fetch_domains = tuple(getattr(tool_catalog.web_fetch, "allowed_domains", ()) or ())

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

    def _http() -> httpx.Client:
        return http_client or shared_sync_http_client()

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

    def _tavily_post_raw(payload: dict[str, Any], *, attempt: int) -> str:
        response = _http().post(
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

    def _fetch_url(
        url: str,
        *,
        max_bytes: int,
    ) -> tuple[bytes, str, Any, str, bool]:
        current_url = url
        client = _http()
        secure_transport = http_client is not None or isinstance(client, httpx.Client)
        pinned_client = client if http_client is not None else None
        current_addresses: tuple[str, ...] | None = None
        response = None
        for _ in range(_WEB_FETCH_MAX_REDIRECTS + 1):
            parsed_current = urllib_parse_module.urlparse(current_url)
            if secure_transport and current_addresses is None:
                port = parsed_current.port or (443 if parsed_current.scheme == "https" else 80)
                current_addresses = _resolve_public_fetch_addresses(
                    str(parsed_current.hostname or ""),
                    port,
                )
            if secure_transport:
                response = request_pinned_fetch_url(
                    client=pinned_client,
                    parsed_url=parsed_current,
                    addresses=current_addresses or (),
                    urllib_parse_module=urllib_parse_module,
                    max_bytes=max_bytes,
                )
            else:
                response = client.get(
                    current_url,
                    headers={"User-Agent": "FocusAgent/1.0 (+https://example.local/focus-agent)"},
                    timeout=30,
                )
            current_addresses = None
            if int(response.status_code) not in _WEB_FETCH_REDIRECT_STATUSES:
                break
            location = (
                response.headers.get("location") if hasattr(response.headers, "get") else None
            )
            if not location:
                break
            next_url = urllib_parse_module.urljoin(current_url, str(location))
            parsed_next = urllib_parse_module.urlparse(next_url)
            if parsed_next.scheme not in {"http", "https"}:
                raise ValueError("Only http and https redirect URLs are supported.")
            policy_violation = _web_fetch_policy_violation(
                parsed_next.hostname,
                blocked_domains=blocked_fetch_domains,
                allowed_domains=allowed_fetch_domains,
            )
            if policy_violation is not None:
                raise ValueError(
                    "Web fetch redirect blocked by access policy "
                    f"({policy_violation['category']}): {policy_violation['message']}"
                )
            if secure_transport:
                try:
                    next_port = parsed_next.port or (443 if parsed_next.scheme == "https" else 80)
                    current_addresses = _resolve_public_fetch_addresses(
                        str(parsed_next.hostname or ""),
                        next_port,
                    )
                except ValueError as exc:
                    raise ValueError(f"Web fetch redirect blocked: {exc}") from exc
            current_url = urllib_parse_module.urlunparse(parsed_next)
        else:
            raise ValueError(f"Web fetch exceeded {_WEB_FETCH_MAX_REDIRECTS} redirects.")
        if response is None:
            raise ValueError("Web fetch failed before issuing a request.")
        response.raise_for_status()
        raw = response.content[:max_bytes]
        content_length = (
            response.headers.get("content-length") if hasattr(response.headers, "get") else None
        )
        try:
            fetch_limited = len(response.content) > len(raw) or int(content_length or 0) > max_bytes
        except (TypeError, ValueError):
            fetch_limited = len(response.content) > len(raw)
        return raw, current_url, response.headers, response.encoding or "utf-8", fetch_limited

    def _record_error(
        errors: list[dict[str, Any]],
        error: _WebSearchProviderError,
    ) -> None:
        errors.append(_provider_error_record(error))

    def _provider_order() -> list[str]:
        providers: list[str] = []

        def _add(provider: str | None) -> None:
            normalized = str(provider or "").strip().lower()
            if normalized in {"tavily", "duckduckgo"} and normalized not in providers:
                providers.append(normalized)

        if preferred_web_search_provider in {"auto", "tavily"}:
            _add("tavily")
            _add(fallback_web_search_provider)
        elif preferred_web_search_provider == "duckduckgo":
            _add("duckduckgo")
        else:
            return []
        return providers

    def _errors_from_exception(error: Exception) -> list[dict[str, Any]]:
        if isinstance(error, _WebSearchProviderError):
            if error.errors:
                return list(error.errors)
            return [_provider_error_record(error)]
        return [
            {
                "provider": "web_search",
                "category": "provider_error",
                "message": str(error),
            }
        ]

    def _attempted_providers_from_errors(errors: list[dict[str, Any]]) -> list[str]:
        attempted: list[str] = []
        for error in errors:
            provider = str(error.get("provider") or "").strip().lower()
            if provider and provider != "web_search" and provider not in attempted:
                attempted.append(provider)
        return attempted

    def _augment_search_payload(
        payload: dict[str, Any],
        *,
        attempted_providers: list[str],
        errors: list[dict[str, Any]],
        fallback_used: bool,
    ) -> dict[str, Any]:
        augmented = {
            **payload,
            "fallback_used": fallback_used,
            "attempted_providers": list(attempted_providers),
            "errors": list(errors),
        }
        filters = payload.get("search_filters")
        if isinstance(filters, dict):
            for key in ("time_range", "include_domains", "exclude_domains"):
                if key in filters:
                    augmented[key] = filters[key]
        return augmented

    def _provider_failure_summary(errors: list[dict[str, Any]]) -> str:
        if not errors:
            return "No web search provider succeeded."
        details = []
        for error in errors:
            provider = error.get("provider") or "unknown"
            category = error.get("category") or "provider_error"
            message = error.get("message") or "provider failed"
            details.append(f"{provider} ({category}): {message}")
        return "No web search provider succeeded: " + "; ".join(details)

    def _emit_provider_attempt(
        *,
        tool_name: str,
        provider: str,
        attempt: int,
        max_attempts: int,
    ) -> None:
        emit_tool_event(
            tool_name=tool_name,
            stage="provider_attempt",
            provider=provider,
            attempt=attempt,
            max_attempts=max_attempts,
        )

    def _emit_provider_success(
        *,
        tool_name: str,
        payload: dict[str, Any],
        attempt: int,
    ) -> None:
        emit_tool_event(
            tool_name=tool_name,
            stage="provider_success",
            provider=payload["provider"],
            attempt=attempt,
            result_count=len(payload["results"]),
        )

    def _emit_provider_error(
        *,
        tool_name: str,
        error: _WebSearchProviderError,
    ) -> None:
        emit_tool_event(
            tool_name=tool_name,
            stage="provider_error",
            provider=error.provider,
            category=error.category,
            retryable=error.retryable,
            status_code=error.status_code,
            attempt=error.attempt,
            error=str(error),
        )

    def _run_tavily_search(
        *,
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
            raw = _tavily_post_raw(payload, attempt=attempt)
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

    def _run_provider_attempt(
        *,
        provider: str,
        query: str,
        max_results: int,
        time_range: str | None,
        include_domains: list[str],
        exclude_domains: list[str],
        tool_name: str,
        attempt: int,
        max_attempts: int,
    ) -> dict[str, Any]:
        _emit_provider_attempt(
            tool_name=tool_name,
            provider=provider,
            attempt=attempt,
            max_attempts=max_attempts,
        )
        try:
            if provider == "tavily":
                payload = _run_tavily_search(
                    query=query,
                    max_results=max_results,
                    attempt=attempt,
                    time_range=time_range,
                    include_domains=include_domains,
                    exclude_domains=exclude_domains,
                )
            elif provider == "duckduckgo":
                payload = _run_duckduckgo_search(
                    query=query,
                    max_results=max_results,
                    attempt=attempt,
                    time_range=time_range,
                    include_domains=include_domains,
                    exclude_domains=exclude_domains,
                )
            else:
                raise _make_provider_error(
                    provider=provider,
                    category="provider_error",
                    message=f"Unsupported web search provider: {provider}",
                    attempt=attempt,
                )
        except _WebSearchProviderError as exc:
            _emit_provider_error(tool_name=tool_name, error=exc)
            raise
        _emit_provider_success(tool_name=tool_name, payload=payload, attempt=attempt)
        return payload

    def _run_tavily_with_retries(
        *,
        query: str,
        max_results: int,
        time_range: str | None,
        include_domains: list[str],
        exclude_domains: list[str],
        tool_name: str,
        errors: list[dict[str, Any]],
    ) -> dict[str, Any]:
        for attempt in range(1, _TAVILY_MAX_ATTEMPTS + 1):
            try:
                return _run_provider_attempt(
                    provider="tavily",
                    query=query,
                    max_results=max_results,
                    time_range=time_range,
                    include_domains=include_domains,
                    exclude_domains=exclude_domains,
                    tool_name=tool_name,
                    attempt=attempt,
                    max_attempts=_TAVILY_MAX_ATTEMPTS,
                )
            except _WebSearchProviderError as exc:
                _record_error(errors, exc)
                if exc.retryable and attempt < _TAVILY_MAX_ATTEMPTS:
                    continue
                raise
        raise _make_provider_error(
            provider="tavily",
            category="provider_error",
            message="Tavily search failed before producing a result.",
        )

    def _run_web_search(
        *,
        query: str,
        max_results: int,
        time_range: Any = None,
        include_domains: Any = None,
        exclude_domains: Any = None,
        tool_name: str,
    ) -> str:
        normalized_query, query_truncated = _normalize_web_search_query(query)
        normalized_time_range, normalized_include_domains, normalized_exclude_domains = (
            _validate_search_filters(
                time_range=time_range,
                include_domains=include_domains,
                exclude_domains=exclude_domains,
            )
        )
        try:
            capped_results = max(1, min(int(max_results), 10))
        except (TypeError, ValueError) as exc:
            message = "max_results must be an integer."
            emit_tool_event(tool_name=tool_name, stage="error", error=message)
            raise ValueError(message) from exc
        emit_tool_event(
            tool_name=tool_name,
            stage="start",
            query=normalized_query,
            max_results=capped_results,
            query_truncated=query_truncated,
            time_range=normalized_time_range,
            include_domains=normalized_include_domains,
            exclude_domains=normalized_exclude_domains,
        )
        if not normalized_query:
            message = "Query must not be empty."
            emit_tool_event(tool_name=tool_name, stage="error", error=message)
            raise ValueError(message)
        if not web_search_config.enabled:
            message = "web_search is disabled by tools configuration."
            emit_tool_event(tool_name=tool_name, stage="error", error=message)
            raise RuntimeError(message)

        providers = _provider_order()
        if not providers:
            message = "No primary web search provider is configured."
            emit_tool_event(tool_name=tool_name, stage="error", error=message)
            raise RuntimeError(message)

        attempted_providers: list[str] = []
        errors: list[dict[str, Any]] = []
        primary_provider = providers[0]
        for provider in providers:
            if provider not in attempted_providers:
                attempted_providers.append(provider)
            try:
                if provider == "tavily":
                    payload = _run_tavily_with_retries(
                        query=normalized_query,
                        max_results=capped_results,
                        time_range=normalized_time_range,
                        include_domains=normalized_include_domains,
                        exclude_domains=normalized_exclude_domains,
                        tool_name=tool_name,
                        errors=errors,
                    )
                else:
                    try:
                        payload = _run_provider_attempt(
                            provider=provider,
                            query=normalized_query,
                            max_results=capped_results,
                            time_range=normalized_time_range,
                            include_domains=normalized_include_domains,
                            exclude_domains=normalized_exclude_domains,
                            tool_name=tool_name,
                            attempt=1,
                            max_attempts=1,
                        )
                    except _WebSearchProviderError as exc:
                        _record_error(errors, exc)
                        raise
            except _WebSearchProviderError:
                continue

            payload = _augment_search_payload(
                payload,
                attempted_providers=attempted_providers,
                errors=errors,
                fallback_used=provider != primary_provider,
            )
            if query_truncated:
                payload["query_truncated"] = True
            result = json.dumps(payload, ensure_ascii=False)
            emit_tool_event(
                tool_name=tool_name,
                stage="end",
                provider=payload["provider"],
                result_count=len(payload["results"]),
                fallback_used=payload["fallback_used"],
                output=result[:800],
            )
            return result

        message = _provider_failure_summary(errors)
        category = (
            str(errors[-1].get("category") or "provider_error") if errors else "provider_error"
        )
        emit_tool_event(
            tool_name=tool_name,
            stage="error",
            category=category,
            error=message,
        )
        raise _make_provider_error(
            provider="web_search",
            category=category,
            message=message,
            errors=errors,
        )

    def _fallback_web_search(_error: Exception, args: dict[str, Any]) -> str:
        normalized_query, query_truncated = _normalize_web_search_query(
            str(args.get("query") or "")
        )
        requested_results = int(args.get("max_results") or 5)
        capped_results = max(1, min(requested_results, 10))
        normalized_time_range, normalized_include_domains, normalized_exclude_domains = (
            _validate_search_filters(
                time_range=args.get("time_range"),
                include_domains=args.get("include_domains"),
                exclude_domains=args.get("exclude_domains"),
            )
        )
        should_try_duckduckgo = (
            preferred_web_search_provider == "duckduckgo"
            or fallback_web_search_provider == "duckduckgo"
        )
        if not should_try_duckduckgo:
            raise RuntimeError("No fallback web search provider is configured.")
        errors = _errors_from_exception(_error)
        attempted_providers = _attempted_providers_from_errors(errors)
        if "duckduckgo" not in attempted_providers:
            attempted_providers.append("duckduckgo")
        payload = _run_provider_attempt(
            provider="duckduckgo",
            query=normalized_query,
            max_results=capped_results,
            time_range=normalized_time_range,
            include_domains=normalized_include_domains,
            exclude_domains=normalized_exclude_domains,
            tool_name="web_search",
            attempt=1,
            max_attempts=1,
        )
        payload = _augment_search_payload(
            payload,
            attempted_providers=attempted_providers,
            errors=errors,
            fallback_used=True,
        )
        if query_truncated:
            payload["query_truncated"] = True
        result = json.dumps(payload, ensure_ascii=False)
        emit_tool_event(
            tool_name="web_search",
            stage="delta",
            provider="duckduckgo",
            message="Primary web search failed; using DuckDuckGo fallback.",
            output=result[:800],
        )
        return result

    @tool
    def web_fetch(url: str, max_chars: int | None = None) -> str:
        """Fetch a readable HTTP or HTTPS page with a bounded head/tail preview."""
        tool_name = "web_fetch"
        emit_tool_event(tool_name=tool_name, stage="start", url=url, max_chars=max_chars)
        try:
            parsed = urllib_parse_module.urlparse(url.strip())
            if parsed.scheme not in {"http", "https"}:
                raise ValueError("Only http and https URLs are supported.")
            policy_violation = _web_fetch_policy_violation(
                parsed.hostname,
                blocked_domains=blocked_fetch_domains,
                allowed_domains=allowed_fetch_domains,
            )
            if policy_violation is not None:
                emit_tool_event(
                    tool_name=tool_name,
                    stage="blocked",
                    url=url,
                    **policy_violation,
                )
                raise ValueError(
                    "Web fetch blocked by access policy "
                    f"({policy_violation['category']}): {policy_violation['message']}"
                )
            requested_chars = (
                tool_catalog.web_fetch.default_max_chars if max_chars is None else int(max_chars)
            )
            capped_chars = max(1, min(requested_chars, tool_catalog.web_fetch.max_chars_cap))
            raw, final_url, headers, charset, fetch_limited = _fetch_url(
                urllib_parse_module.urlunparse(parsed),
                max_bytes=_WEB_FETCH_MAX_BYTES,
            )
            content_type = headers.get("content-type", "") if hasattr(headers, "get") else ""
            binary_kind = _binary_payload_kind(raw, content_type)
            if binary_kind:
                payload = {
                    "url": url,
                    "final_url": final_url,
                    "title": "",
                    "content_type": content_type,
                    "content": "",
                    "truncated": False,
                    "binary": True,
                    "status": "error",
                    "error": (
                        f"URL returned {binary_kind}, not readable text. "
                        "Download it with a file-aware tool instead of treating it as page text."
                    ),
                }
                result = json.dumps(payload, ensure_ascii=False)
                emit_tool_event(tool_name=tool_name, stage="end", output=result[:800])
                return result
            decoded = raw.decode(charset, errors="replace")
            title = ""
            published_at = None
            if "html" in content_type.lower() or "<html" in decoded[:500].lower():
                parser = _ReadableHTMLExtractor(base_url=final_url)
                parser.feed(decoded)
                parser.close()
                title = parser.title
                content = parser.text
                published_at = parser.published_at
            else:
                content = decoded.strip()
            if not content or title.strip().lower().rstrip(".!…") in {
                "just a moment",
                "access denied",
                "attention required",
                "attention required | cloudflare",
                "verify you are human",
                "robot or human",
            }:
                return json.dumps(
                    {
                        "url": url,
                        "final_url": final_url,
                        "title": title,
                        "status": "error",
                        "error": "Page is empty or blocked by an access challenge; use another primary source.",
                        "content": "",
                    },
                    ensure_ascii=False,
                )
            window_budget = (
                capped_chars
                if len(content) <= capped_chars
                else max(1, capped_chars - len(_WEB_FETCH_TRUNCATION_MARKER))
            )
            head, tail, truncated = _head_tail_text_window(content, window_budget)
            continuation: dict[str, Any] | None = None
            displayed_content = content
            if truncated:
                displayed_content = f"{head}{_WEB_FETCH_TRUNCATION_MARKER}{tail}"
                if capped_chars <= len(_WEB_FETCH_TRUNCATION_MARKER):
                    head, tail = content[:capped_chars], ""
                    displayed_content = head
                if callable(save_tool_observation):
                    observation_id = uuid.uuid4().hex
                    try:
                        thread_id = (
                            get_current_thread_id() if callable(get_current_thread_id) else None
                        )
                        saved = save_tool_observation(
                            tool_name=tool_name,
                            tool_call_id=observation_id,
                            content=content,
                            thread_id=thread_id,
                        )
                    except Exception as exc:  # noqa: BLE001
                        emit_tool_event(
                            tool_name=tool_name,
                            stage="delta",
                            message="Full web content could not be saved for continuation.",
                            error=str(exc),
                        )
                        saved = None
                    if saved:
                        artifact_ref = f"tool-observation://{tool_name}/{observation_id}"
                        continuation = {
                            "artifact_ref": artifact_ref,
                            "tool": "artifact_read",
                            "args": {
                                "artifact_id": artifact_ref,
                                "offset": len(head),
                                "limit": capped_chars,
                            },
                            "offset": len(head),
                            "limit": capped_chars,
                            "total_chars": len(content),
                            "hint": (
                                "Call artifact_read using the supplied args "
                                "to page through the omitted middle."
                            ),
                        }
                if continuation is None:
                    continuation = {
                        "available": False,
                        "total_chars": len(content),
                        "hint": (
                            "Full text was not saved in this runtime; call web_fetch again "
                            "with a larger max_chars value to inspect more of the page."
                        ),
                    }
            payload = {
                "url": url,
                "final_url": final_url,
                "title": title,
                "content_type": content_type,
                "content": displayed_content,
                "content_chars": len(content),
                "shown_chars": len(displayed_content),
                "truncated": truncated,
                "fetch_limited": fetch_limited,
                "observed_at": datetime.now(UTC).isoformat(),
                "published_at": published_at,
                "source_type": "page",
            }
            if continuation is not None:
                payload["continuation"] = continuation
                payload["total_chars"] = len(content)
                artifact_ref = continuation.get("artifact_ref")
                if artifact_ref:
                    payload["artifact_ref"] = artifact_ref
                    payload["next_offset"] = len(head)
            result = json.dumps(payload, ensure_ascii=False)
            emit_tool_event(tool_name=tool_name, stage="end", output=result[:800])
            return result
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(tool_name=tool_name, stage="error", error=str(exc), url=url)
            raise

    @tool
    def web_search(
        query: str,
        max_results: int | None = None,
        time_range: str | None = None,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
    ) -> str:
        """Search the live web with optional freshness and domain filters."""
        requested_results = 5 if max_results is None else int(max_results)
        return _run_web_search(
            query=query,
            max_results=requested_results,
            time_range=time_range,
            include_domains=include_domains,
            exclude_domains=exclude_domains,
            tool_name="web_search",
        )

    return (
        {
            "web_fetch": web_fetch,
            "web_search": web_search,
        },
        {
            "web_fetch": {
                "parallel_safe": True,
                "timeout_seconds": 45,
                "validator": _validate_web_fetch_args,
                "max_observation_chars": 7000,
            },
            "web_search": {
                "parallel_safe": True,
                "timeout_seconds": 45,
                "validator": _validate_web_search_args,
                "fallback_group": "web_search",
                "fallback_handler": _fallback_web_search,
                "max_observation_chars": 7000,
            },
        },
    )
