from __future__ import annotations

import ipaddress
import json
from collections.abc import Callable
from html.parser import HTMLParser
from typing import Any
from urllib import error as stdlib_urllib_error
from urllib import parse as stdlib_urllib_parse
from urllib import request as stdlib_urllib_request

from langchain.tools import tool

from .common import _collapse_whitespace, _require_non_empty_text_arg

_TAVILY_MAX_ATTEMPTS = 2
_WEB_SEARCH_ERROR_CATEGORIES = {
    "missing_api_key",
    "timeout",
    "rate_limited",
    "provider_error",
    "invalid_payload",
    "empty_results",
}


class _WebSearchProviderError(RuntimeError):
    def __init__(
        self,
        *,
        provider: str,
        category: str,
        message: str,
        retryable: bool = False,
        status_code: int | None = None,
        attempt: int | None = None,
        errors: list[dict[str, Any]] | None = None,
    ) -> None:
        normalized_category = (
            category if category in _WEB_SEARCH_ERROR_CATEGORIES else "provider_error"
        )
        self.provider = provider
        self.category = normalized_category
        self.retryable = retryable
        self.status_code = status_code
        self.attempt = attempt
        self.errors = list(errors or [])
        super().__init__(message)


def _normalize_search_result(*, title: Any, url: Any, content: Any) -> dict[str, str]:
    return {
        "title": str(title or ""),
        "url": str(url or ""),
        "content": str(content or ""),
    }


class _ReadableHTMLExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        lowered = tag.lower()
        if lowered in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        elif lowered == "title":
            self._in_title = True
        elif lowered in {"p", "div", "br", "li", "section", "article", "h1", "h2", "h3"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        elif lowered == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
        if self._skip_depth == 0 and not self._in_title:
            self.text_parts.append(text)

    @property
    def title(self) -> str:
        return _collapse_whitespace(" ".join(self.title_parts))

    @property
    def text(self) -> str:
        return _collapse_whitespace("\n".join(self.text_parts))


def _is_blocked_fetch_host(host: str | None) -> bool:
    if not host:
        return True
    normalized = host.strip().lower().strip("[]")
    if normalized in {"localhost", "localhost.localdomain"} or normalized.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
    )


def _normalize_domain_rule(rule: Any) -> str:
    normalized = str(rule or "").strip().lower()
    if not normalized:
        return ""
    if "://" in normalized:
        parsed = stdlib_urllib_parse.urlparse(normalized)
        normalized = parsed.hostname or parsed.netloc or parsed.path
    normalized = normalized.split("/", 1)[0].strip().strip("[]").rstrip(".")
    if normalized.startswith("www."):
        normalized = normalized[4:]
    return normalized


def _normalize_policy_host(host: str | None) -> str:
    normalized = str(host or "").strip().lower().strip("[]").rstrip(".")
    if normalized.startswith("www."):
        normalized = normalized[4:]
    return normalized


def _host_matches_domain_rule(host: str, rule: str) -> bool:
    if not host or not rule:
        return False
    if rule.startswith("*."):
        suffix = rule[2:]
        return host.endswith(f".{suffix}")
    return host == rule or host.endswith(f".{rule}")


def _web_fetch_policy_violation(
    host: str | None,
    *,
    blocked_domains: tuple[str, ...],
    allowed_domains: tuple[str, ...],
) -> dict[str, str] | None:
    normalized_host = _normalize_policy_host(host)
    if not normalized_host:
        return {
            "category": "invalid_host",
            "host": "",
            "rule": "",
            "message": "URL must include a valid hostname.",
        }
    if _is_blocked_fetch_host(normalized_host):
        return {
            "category": "blocked_host",
            "host": normalized_host,
            "rule": "local_or_private_network",
            "message": "Refusing to fetch localhost, private, reserved, or link-local hosts.",
        }

    for raw_rule in blocked_domains:
        rule = _normalize_domain_rule(raw_rule)
        if _host_matches_domain_rule(normalized_host, rule):
            return {
                "category": "blocked_domain",
                "host": normalized_host,
                "rule": rule,
                "message": f"Refusing to fetch blocked domain: {rule}.",
            }

    normalized_allowlist = tuple(
        rule for rule in (_normalize_domain_rule(item) for item in allowed_domains) if rule
    )
    if normalized_allowlist and not any(
        _host_matches_domain_rule(normalized_host, rule) for rule in normalized_allowlist
    ):
        return {
            "category": "not_in_allowlist",
            "host": normalized_host,
            "rule": ",".join(normalized_allowlist),
            "message": "Refusing to fetch a domain outside the configured allowlist.",
        }
    return None


def _is_timeout_exception(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    reason = getattr(exc, "reason", None)
    if isinstance(reason, TimeoutError):
        return True
    message = str(reason if reason is not None else exc).lower()
    return "timed out" in message or "timeout" in message


def _provider_error_record(error: _WebSearchProviderError) -> dict[str, Any]:
    record: dict[str, Any] = {
        "provider": error.provider,
        "category": error.category,
        "message": str(error),
    }
    if error.status_code is not None:
        record["status_code"] = error.status_code
    if error.attempt is not None:
        record["attempt"] = error.attempt
    return record


def build_web_tools(
    *,
    web_search_config: Any,
    tool_catalog: Any,
    resolved_env: Any,
    emit_tool_event: Callable[..., None],
    urllib_request_module: Any = stdlib_urllib_request,
    urllib_error_module: Any = stdlib_urllib_error,
    urllib_parse_module: Any = stdlib_urllib_parse,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    def _validate_web_fetch_args(args: dict[str, Any]) -> None:
        _require_non_empty_text_arg(args, "url")

    def _validate_web_search_args(args: dict[str, Any]) -> None:
        _require_non_empty_text_arg(args, "query")

    preferred_web_search_provider = str(web_search_config.provider or "auto").strip().lower() or "auto"
    fallback_web_search_provider = (
        str(web_search_config.fallback_provider).strip().lower()
        if web_search_config.fallback_provider
        else None
    )
    tavily_api_key = (
        (
            resolved_env.get(web_search_config.api_key_env, "").strip()
            if web_search_config.api_key_env
            else ""
        )
        or str(web_search_config.api_key_default or "").strip()
    )
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
        return {
            **payload,
            "fallback_used": fallback_used,
            "attempted_providers": list(attempted_providers),
            "errors": list(errors),
        }

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

    def _run_tavily_search(*, query: str, max_results: int, attempt: int) -> dict[str, Any]:
        if not tavily_api_key:
            raise _make_provider_error(
                provider="tavily",
                category="missing_api_key",
                message="TAVILY_API_KEY is not configured.",
                attempt=attempt,
            )
        payload = json.dumps(
            {
                "query": query,
                "max_results": max_results,
                "include_answer": True,
            }
        ).encode("utf-8")
        req = urllib_request_module.Request(
            "https://api.tavily.com/search",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {tavily_api_key}",
            },
            method="POST",
        )
        try:
            with urllib_request_module.urlopen(req, timeout=30) as response:
                raw = response.read().decode("utf-8")
        except urllib_error_module.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            status_code = int(exc.code)
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
            raise _make_provider_error(
                provider="tavily",
                category=category,
                message=f"Tavily search failed with HTTP {status_code}: {body[:300]}",
                retryable=retryable,
                status_code=status_code,
                attempt=attempt,
            ) from exc
        except urllib_error_module.URLError as exc:
            category = "timeout" if _is_timeout_exception(exc) else "provider_error"
            raise _make_provider_error(
                provider="tavily",
                category=category,
                message=f"Tavily search failed: {exc.reason}",
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

        results = data.get("results")
        if not isinstance(results, list):
            raise _make_provider_error(
                provider="tavily",
                category="invalid_payload",
                message="Tavily search returned an unusable payload.",
                attempt=attempt,
            )

        normalized_results: list[dict[str, str]] = []
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
        }

    def _run_duckduckgo_search(*, query: str, max_results: int, attempt: int) -> dict[str, Any]:
        try:
            from ddgs import DDGS
        except ImportError as exc:
            raise _make_provider_error(
                provider="duckduckgo",
                category="provider_error",
                message="DuckDuckGo fallback is unavailable because 'ddgs' is not installed.",
                attempt=attempt,
            ) from exc

        try:
            with DDGS(timeout=30) as ddgs:
                raw_results = list(
                    ddgs.text(
                        query,
                        region="wt-wt",
                        safesearch="moderate",
                        max_results=max_results,
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

        normalized_results: list[dict[str, str]] = []
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
        }

    def _run_provider_attempt(
        *,
        provider: str,
        query: str,
        max_results: int,
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
                )
            elif provider == "duckduckgo":
                payload = _run_duckduckgo_search(
                    query=query,
                    max_results=max_results,
                    attempt=attempt,
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
        tool_name: str,
        errors: list[dict[str, Any]],
    ) -> dict[str, Any]:
        for attempt in range(1, _TAVILY_MAX_ATTEMPTS + 1):
            try:
                return _run_provider_attempt(
                    provider="tavily",
                    query=query,
                    max_results=max_results,
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

    def _run_web_search(*, query: str, max_results: int, tool_name: str) -> str:
        normalized_query = query.strip()
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
                        tool_name=tool_name,
                        errors=errors,
                    )
                else:
                    try:
                        payload = _run_provider_attempt(
                            provider=provider,
                            query=normalized_query,
                            max_results=capped_results,
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
        category = str(errors[-1].get("category") or "provider_error") if errors else "provider_error"
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
        normalized_query = str(args.get("query") or "").strip()
        requested_results = int(args.get("max_results") or 5)
        capped_results = max(1, min(requested_results, 10))
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
        """Fetch and extract readable text from a user-provided HTTP or HTTPS URL."""
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
                tool_catalog.web_fetch.default_max_chars
                if max_chars is None
                else int(max_chars)
            )
            capped_chars = max(1, min(requested_chars, tool_catalog.web_fetch.max_chars_cap))
            request = urllib_request_module.Request(
                urllib_parse_module.urlunparse(parsed),
                headers={"User-Agent": "FocusAgent/1.0 (+https://example.local/focus-agent)"},
                method="GET",
            )
            with urllib_request_module.urlopen(request, timeout=30) as response:
                raw = response.read(min(capped_chars * 4, tool_catalog.web_fetch.max_chars_cap * 4))
                final_url = response.geturl() if hasattr(response, "geturl") else urllib_parse_module.urlunparse(parsed)
                headers = getattr(response, "headers", {}) or {}
                content_type = headers.get("content-type", "") if hasattr(headers, "get") else ""
                charset = (
                    headers.get_content_charset()
                    if hasattr(headers, "get_content_charset")
                    else None
                ) or "utf-8"
            decoded = raw.decode(charset, errors="replace")
            title = ""
            if "html" in content_type.lower() or "<html" in decoded[:500].lower():
                parser = _ReadableHTMLExtractor()
                parser.feed(decoded)
                title = parser.title
                content = parser.text
            else:
                content = _collapse_whitespace(decoded)
            truncated = len(content) > capped_chars
            payload = {
                "url": url,
                "final_url": final_url,
                "title": title,
                "content_type": content_type,
                "content": content[:capped_chars],
                "truncated": truncated,
            }
            result = json.dumps(payload, ensure_ascii=False)
            emit_tool_event(tool_name=tool_name, stage="end", output=result[:800])
            return result
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(tool_name=tool_name, stage="error", error=str(exc), url=url)
            raise

    @tool
    def web_search(query: str, max_results: int | None = None) -> str:
        """Search the live web with Tavily first and DuckDuckGo as a fallback."""
        requested_results = 5 if max_results is None else int(max_results)
        return _run_web_search(query=query, max_results=requested_results, tool_name="web_search")

    return (
        {
            "web_fetch": web_fetch,
            "web_search": web_search,
        },
        {
            "web_fetch": {
                "parallel_safe": True,
                "validator": _validate_web_fetch_args,
                "max_observation_chars": 7000,
            },
            "web_search": {
                "parallel_safe": True,
                "validator": _validate_web_search_args,
                "fallback_group": "web_search",
                "fallback_handler": _fallback_web_search,
                "max_observation_chars": 7000,
            },
        },
    )
