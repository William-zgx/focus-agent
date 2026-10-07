from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx

from .web_helpers import (
    _TAVILY_MAX_ATTEMPTS,
    _normalize_search_domains,
    _normalize_search_time_range,
    _provider_error_record,
    _unsupported_search_time_range,
    _WebSearchProviderError,
)
from .web_search_providers import (
    _make_provider_error,
    _run_duckduckgo_search,
    _run_tavily_search,
)

_TAVILY_MAX_QUERY_CHARS = 400


def _normalize_web_search_query(query: str) -> tuple[str, bool]:
    normalized = " ".join(str(query or "").split())
    if len(normalized) <= _TAVILY_MAX_QUERY_CHARS:
        return normalized, False
    truncated = normalized[:_TAVILY_MAX_QUERY_CHARS].rstrip()
    return truncated, True


def _validate_search_filters(
    *,
    time_range: Any = None,
    include_domains: Any = None,
    exclude_domains: Any = None,
) -> tuple[str | None, list[str], list[str]]:
    # Explicit dates ("2026-01-01") cannot be enforced as a provider window; searching
    # unfiltered with a visible note costs less than failing the whole round.
    normalized_time_range = (
        None
        if _unsupported_search_time_range(time_range)
        else _normalize_search_time_range(time_range)
    )
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


def _record_error(
    errors: list[dict[str, Any]],
    error: _WebSearchProviderError,
) -> None:
    errors.append(_provider_error_record(error))


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
    requested_time_range: Any = None,
) -> dict[str, Any]:
    augmented = {
        **payload,
        "fallback_used": fallback_used,
        "attempted_providers": list(attempted_providers),
        "errors": list(errors),
    }
    ignored_time_range = _unsupported_search_time_range(requested_time_range)
    if ignored_time_range is not None:
        augmented["time_range_ignored"] = {
            "requested": ignored_time_range,
            "note": (
                "time_range only accepts day, week, month or year, so this search ran "
                "without a time filter. Put explicit dates or years in the query instead."
            ),
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


def build_web_search_runner(
    *,
    web_search_config: Any,
    resolved_env: Any,
    emit_tool_event: Callable[..., None],
    http: Callable[[], httpx.Client],
) -> tuple[Callable[..., str], Callable[[Exception, dict[str, Any]], str]]:
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
                    http=http,
                    tavily_api_key=tavily_api_key,
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
                requested_time_range=time_range,
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
            requested_time_range=args.get("time_range"),
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

    return _run_web_search, _fallback_web_search
