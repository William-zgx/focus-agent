from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx

from .web_helpers import (
    _TAVILY_MAX_ATTEMPTS,
    _date_range_window,
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
    unsupported_time_range = _unsupported_search_time_range(time_range)
    normalized_time_range = (
        _date_range_window(unsupported_time_range)
        if unsupported_time_range
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
    applied_window = _date_range_window(ignored_time_range) if ignored_time_range else None
    if ignored_time_range is not None and applied_window:
        augmented["time_range_mapped"] = {
            "requested": ignored_time_range,
            "applied": applied_window,
            "note": (
                "Exact date ranges are not supported; applied the smallest covering window. "
                "Check each result's publication date against the requested range."
            ),
        }
    elif ignored_time_range is not None:
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


class _WebSearchRunner:
    """Runs the configured provider chain (Tavily with retries, then DuckDuckGo)."""

    def __init__(
        self,
        *,
        web_search_config: Any,
        resolved_env: Any,
        emit_tool_event: Callable[..., None],
        http: Callable[[], httpx.Client],
    ) -> None:
        self._config = web_search_config
        self._emit = emit_tool_event
        self._http = http
        self._preferred_provider = (
            str(web_search_config.provider or "auto").strip().lower() or "auto"
        )
        self._fallback_provider = (
            str(web_search_config.fallback_provider).strip().lower()
            if web_search_config.fallback_provider
            else None
        )
        self._tavily_api_key = (
            resolved_env.get(web_search_config.api_key_env, "").strip()
            if web_search_config.api_key_env
            else ""
        ) or str(web_search_config.api_key_default or "").strip()

    def _provider_order(self) -> list[str]:
        providers: list[str] = []

        def _add(provider: str | None) -> None:
            normalized = str(provider or "").strip().lower()
            if normalized in {"tavily", "duckduckgo"} and normalized not in providers:
                providers.append(normalized)

        if self._preferred_provider in {"auto", "tavily"}:
            _add("tavily")
            _add(self._fallback_provider)
        elif self._preferred_provider == "duckduckgo":
            _add("duckduckgo")
        else:
            return []
        return providers

    def _run_provider_attempt(
        self,
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
        self._emit(
            tool_name=tool_name,
            stage="provider_attempt",
            provider=provider,
            attempt=attempt,
            max_attempts=max_attempts,
        )
        try:
            if provider == "tavily":
                payload = _run_tavily_search(
                    http=self._http,
                    tavily_api_key=self._tavily_api_key,
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
            self._emit(
                tool_name=tool_name,
                stage="provider_error",
                provider=exc.provider,
                category=exc.category,
                retryable=exc.retryable,
                status_code=exc.status_code,
                attempt=exc.attempt,
                error=str(exc),
            )
            raise
        self._emit(
            tool_name=tool_name,
            stage="provider_success",
            provider=payload["provider"],
            attempt=attempt,
            result_count=len(payload["results"]),
        )
        return payload

    def _run_provider_with_retries(
        self,
        *,
        provider: str,
        errors: list[dict[str, Any]],
        **search_args: Any,
    ) -> dict[str, Any]:
        max_attempts = _TAVILY_MAX_ATTEMPTS if provider == "tavily" else 1
        for attempt in range(1, max_attempts + 1):
            try:
                return self._run_provider_attempt(
                    provider=provider,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    **search_args,
                )
            except _WebSearchProviderError as exc:
                _record_error(errors, exc)
                if exc.retryable and attempt < max_attempts:
                    continue
                raise
        raise _make_provider_error(
            provider="tavily",
            category="provider_error",
            message="Tavily search failed before producing a result.",
        )

    def _fail(self, *, tool_name: str, message: str, error_type: type[Exception]) -> Exception:
        self._emit(tool_name=tool_name, stage="error", error=message)
        return error_type(message)

    def run(
        self,
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
            raise self._fail(
                tool_name=tool_name,
                message="max_results must be an integer.",
                error_type=ValueError,
            ) from exc
        self._emit(
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
            raise self._fail(
                tool_name=tool_name, message="Query must not be empty.", error_type=ValueError
            )
        if not self._config.enabled:
            raise self._fail(
                tool_name=tool_name,
                message="web_search is disabled by tools configuration.",
                error_type=RuntimeError,
            )
        providers = self._provider_order()
        if not providers:
            raise self._fail(
                tool_name=tool_name,
                message="No primary web search provider is configured.",
                error_type=RuntimeError,
            )

        attempted_providers: list[str] = []
        errors: list[dict[str, Any]] = []
        for provider in providers:
            if provider not in attempted_providers:
                attempted_providers.append(provider)
            try:
                payload = self._run_provider_with_retries(
                    provider=provider,
                    errors=errors,
                    query=normalized_query,
                    max_results=capped_results,
                    time_range=normalized_time_range,
                    include_domains=normalized_include_domains,
                    exclude_domains=normalized_exclude_domains,
                    tool_name=tool_name,
                )
            except _WebSearchProviderError:
                continue

            payload = _augment_search_payload(
                payload,
                attempted_providers=attempted_providers,
                errors=errors,
                fallback_used=provider != providers[0],
                requested_time_range=time_range,
            )
            if query_truncated:
                payload["query_truncated"] = True
            result = json.dumps(payload, ensure_ascii=False)
            self._emit(
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
        self._emit(
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

    def fallback(self, _error: Exception, args: dict[str, Any]) -> str:
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
        if "duckduckgo" not in {self._preferred_provider, self._fallback_provider}:
            raise RuntimeError("No fallback web search provider is configured.")
        errors = _errors_from_exception(_error)
        attempted_providers = _attempted_providers_from_errors(errors)
        if "duckduckgo" not in attempted_providers:
            attempted_providers.append("duckduckgo")
        payload = self._run_provider_attempt(
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
        self._emit(
            tool_name="web_search",
            stage="delta",
            provider="duckduckgo",
            message="Primary web search failed; using DuckDuckGo fallback.",
            output=result[:800],
        )
        return result


def build_web_search_runner(
    *,
    web_search_config: Any,
    resolved_env: Any,
    emit_tool_event: Callable[..., None],
    http: Callable[[], httpx.Client],
) -> tuple[Callable[..., str], Callable[[Exception, dict[str, Any]], str]]:
    runner = _WebSearchRunner(
        web_search_config=web_search_config,
        resolved_env=resolved_env,
        emit_tool_event=emit_tool_event,
        http=http,
    )

    def _fallback_web_search(error: Exception, args: dict[str, Any]) -> str:
        return runner.fallback(error, args)

    return runner.run, _fallback_web_search
