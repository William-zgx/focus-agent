"""Shared helpers for default web tools."""

from __future__ import annotations

import ipaddress
from html.parser import HTMLParser
from typing import Any
from urllib import parse as stdlib_urllib_parse

from .common import _collapse_whitespace

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
