"""Shared helpers for default web tools."""

from __future__ import annotations

import ipaddress
import re
import socket
from collections.abc import Mapping, Sequence
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


_SEARCH_TIME_RANGES = {
    "d": "day",
    "day": "day",
    "24h": "day",
    "1d": "day",
    "w": "week",
    "week": "week",
    "7d": "week",
    "m": "month",
    "month": "month",
    "30d": "month",
    "y": "year",
    "year": "year",
    "365d": "year",
}

_SEARCH_DOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
_SEARCH_METADATA_KEYS = (
    "published_date",
    "published_at",
    "published",
    "publishedDate",
    "publication_date",
    "published_on",
    "published_time",
    "last_updated",
    "updated_at",
    "date",
    "author",
    "source",
    "source_name",
    "domain",
    "score",
    "favicon",
    "category",
)


def _normalize_search_time_range(value: Any) -> str | None:
    if value is None or not str(value).strip():
        return None
    normalized = str(value).strip().lower()
    canonical = _SEARCH_TIME_RANGES.get(normalized)
    if canonical is None:
        choices = ", ".join(("day", "week", "month", "year"))
        raise ValueError(f"time_range must be one of: {choices}.")
    return canonical


def _ddgs_time_range(value: str | None) -> str | None:
    return {"day": "d", "week": "w", "month": "m", "year": "y"}.get(value or "")


def _normalize_search_domains(value: Any, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_values = [part.strip() for part in value.split(",")]
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        raw_values = list(value)
    else:
        raise ValueError(f"{field_name} must be a list of domain names.")

    domains: list[str] = []
    for raw_value in raw_values:
        raw = str(raw_value or "").strip().lower()
        if not raw:
            raise ValueError(f"{field_name} contains an empty domain.")
        wildcard = raw.startswith("*.")
        candidate = raw[2:] if wildcard else raw
        if "://" in candidate:
            parsed = stdlib_urllib_parse.urlparse(candidate)
        else:
            parsed = stdlib_urllib_parse.urlparse(f"//{candidate}")
        host = parsed.hostname or ""
        if not host:
            raise ValueError(f"{field_name} contains an invalid domain: {raw_value!r}.")
        try:
            host = host.encode("idna").decode("ascii").lower().rstrip(".")
        except UnicodeError as exc:
            raise ValueError(f"{field_name} contains an invalid domain: {raw_value!r}.") from exc
        if not _SEARCH_DOMAIN_RE.fullmatch(host):
            raise ValueError(f"{field_name} contains an invalid domain: {raw_value!r}.")
        normalized = f"*.{host}" if wildcard else host
        if normalized not in domains:
            domains.append(normalized)
    return domains


def _normalize_search_result(
    *, title: Any, url: Any, content: Any, metadata: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "title": str(title or ""),
        "url": str(url or ""),
        "content": str(content or ""),
    }
    if metadata:
        for key in _SEARCH_METADATA_KEYS:
            value = metadata.get(key)
            if value not in (None, ""):
                result[key] = value
        if "published_date" not in result:
            for alias in (
                "published_at",
                "published",
                "publishedDate",
                "publication_date",
                "published_on",
                "published_time",
                "date",
            ):
                if alias in result:
                    result["published_date"] = result[alias]
                    break
    return result


class _ReadableHTMLExtractor(HTMLParser):
    _VOID_TAGS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self, *, base_url: str = ""):
        super().__init__()
        self._base_url = base_url
        self.title_parts: list[str] = []
        self._content_text_parts: list[str] = []
        self._fallback_text_parts: list[str] = []
        self._link_stack: list[dict[str, Any]] = []
        self._skip_depth = 0
        self._in_title = False
        self._content_depth = 0
        self._open_tags: list[tuple[str, bool]] = []
        self.published_at: str | None = None

    def _append(self, value: str) -> None:
        if not value or self._skip_depth or self._in_title:
            return
        if self._link_stack:
            self._append_to(self._link_stack[-1]["parts"], value)
            return
        self._append_to(self._fallback_text_parts, value)
        if self._content_depth:
            self._append_to(self._content_text_parts, value)

    @staticmethod
    def _append_to(parts: list[str], value: str) -> None:
        if not parts or parts[-1].endswith("\n"):
            parts.append(value)
        elif parts[-1].endswith(" ") or value[:1] in ".,;:!?)]":
            parts[-1] += value
        else:
            parts[-1] += f" {value}"

    def _append_layout(self, value: str) -> None:
        if self._skip_depth or self._in_title:
            return
        if self._link_stack:
            self._link_stack[-1]["parts"].append(value)
            return
        self._fallback_text_parts.append(value)
        if self._content_depth:
            self._content_text_parts.append(value)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
            return
        if lowered == "title":
            self._in_title = True
        attr_map = {str(key).lower(): value for key, value in attrs}
        role_values = str(attr_map.get("role") or "").lower().split()
        is_content_root = lowered in {"main", "article"} or "main" in role_values
        if is_content_root:
            self._content_depth += 1
        if lowered not in self._VOID_TAGS:
            self._open_tags.append((lowered, is_content_root))
        if lowered == "meta" and str(
            attr_map.get("property") or attr_map.get("name") or ""
        ).lower() in {
            "article:published_time",
            "datepublished",
            "date",
            "pubdate",
            "dc.date.issued",
        }:
            self.published_at = (
                self.published_at or str(attr_map.get("content") or "").strip() or None
            )
        if lowered in {"p", "div", "br", "section", "article", "blockquote", "pre"}:
            self._append_layout("\n")
        elif lowered in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._append_layout(f"\n{'#' * int(lowered[1])} ")
        elif lowered == "li":
            self._append_layout("\n- ")
        elif lowered == "a":
            href = str(attr_map.get("href") or "").strip()
            if href and not href.lower().startswith(("javascript:", "data:")):
                href = stdlib_urllib_parse.urljoin(self._base_url, href)
            else:
                href = ""
            self._link_stack.append({"href": href, "parts": []})
        elif lowered == "img":
            source = str(attr_map.get("src") or "").strip()
            alt = str(attr_map.get("alt") or "").strip()
            if source.lower().startswith("data:"):
                self._append_layout("\n")
                self._append(f"[IMAGE: {alt}]" if alt else "[IMAGE]")
            elif source:
                source = stdlib_urllib_parse.urljoin(self._base_url, source)
                self._append_layout("\n")
                self._append(f"![{alt}]({source})")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        elif lowered == "title":
            self._in_title = False
        elif lowered == "a" and self._link_stack:
            self._emit_link(self._link_stack.pop())
        if self._open_tags:
            for index in range(len(self._open_tags) - 1, -1, -1):
                if self._open_tags[index][0] != lowered:
                    continue
                popped = self._open_tags[index:]
                del self._open_tags[index:]
                # Links left open inside a closed ancestor end with it, so their
                # text is not swallowed by the rest of the page.
                if lowered != "a":
                    for _ in range(sum(name == "a" for name, _ in popped)):
                        if self._link_stack:
                            self._emit_link(self._link_stack.pop())
                self._content_depth -= sum(is_root for _, is_root in popped)
                break

    def _emit_link(self, link: dict[str, Any]) -> None:
        text = _collapse_whitespace(" ".join(link["parts"]))
        value = f"[{text}]({link['href']})" if text and link["href"] else text
        if not value:
            return
        if self._link_stack:
            self._append_to(self._link_stack[-1]["parts"], value)
        else:
            self._append_to(self._fallback_text_parts, value)
            if self._content_depth:
                self._append_to(self._content_text_parts, value)

    def close(self) -> None:
        super().close()
        while self._link_stack:
            self._emit_link(self._link_stack.pop())

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
        self._append(text)

    @property
    def title(self) -> str:
        return _collapse_whitespace(" ".join(self.title_parts))

    @property
    def text(self) -> str:
        # An empty main/article root (layout shell) must not hide the real body.
        return _render_text_parts(self._content_text_parts) or _render_text_parts(
            self._fallback_text_parts
        )


def _render_text_parts(parts: list[str]) -> str:
    return "\n".join(
        line for part in parts for raw in part.splitlines() if (line := _collapse_whitespace(raw))
    )


_BINARY_CONTENT_TYPES = (
    "application/octet-stream",
    "application/pdf",
    "application/zip",
    "application/x-gzip",
    "application/x-rar",
    "application/x-7z-compressed",
    "image/",
    "audio/",
    "video/",
)
_BINARY_CONTENT_TYPE_NAMES = {
    "application/octet-stream": "binary content",
    "application/pdf": "PDF document",
    "application/zip": "ZIP archive",
    "application/x-gzip": "gzip archive",
    "application/x-rar": "RAR archive",
    "application/x-7z-compressed": "7-Zip archive",
}
_BINARY_SIGNATURES = (
    (b"%PDF-", "PDF"),
    (b"PK\x03\x04", "ZIP archive"),
    (b"\x89PNG\r\n\x1a\n", "PNG image"),
    (b"\xff\xd8\xff", "JPEG image"),
    (b"GIF8", "GIF image"),
    (b"\x1f\x8b", "gzip archive"),
    (b"Rar!\x1a\x07", "RAR archive"),
    (b"7z\xbc\xaf\x27\x1c", "7-Zip archive"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "OLE compound document"),
    (b"\x7fELF", "ELF executable"),
    (b"OggS", "Ogg media"),
    (b"RIFF", "RIFF media/container"),
)


def _binary_payload_kind(raw: bytes, content_type: str = "") -> str:
    normalized_content_type = content_type.split(";", 1)[0].strip().lower()
    for known_type in _BINARY_CONTENT_TYPES:
        if normalized_content_type == known_type or (
            known_type.endswith("/") and normalized_content_type.startswith(known_type)
        ):
            return _BINARY_CONTENT_TYPE_NAMES.get(
                normalized_content_type,
                "image content"
                if normalized_content_type.startswith("image/")
                else "audio/video content"
                if normalized_content_type.startswith(("audio/", "video/"))
                else known_type.rstrip("/"),
            )
    for signature, kind in _BINARY_SIGNATURES:
        if raw.startswith(signature):
            return kind
    sample = raw[:8192]
    if b"\x00" in sample:
        return "binary data"
    if sample:
        control_count = sum(byte < 9 or 13 < byte < 32 for byte in sample)
        if control_count / len(sample) > 0.02:
            return "binary data"
    return ""


def _head_tail_text_window(content: str, max_chars: int) -> tuple[str, str, bool]:
    if len(content) <= max_chars:
        return content, "", False
    head_budget = max(1, int(max_chars * 0.75))
    tail_budget = max(0, max_chars - head_budget)
    head = content[:head_budget]
    tail = content[-tail_budget:] if tail_budget else ""
    head_break = head.rfind("\n")
    if head_break > head_budget // 2:
        head = head[:head_break]
    tail_break = tail.find("\n")
    if 0 <= tail_break < tail_budget // 2:
        tail = tail[tail_break + 1 :]
    return head, tail, True


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
    return not _is_public_fetch_address(address)


def _is_public_fetch_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    return not (
        not address.is_global
        or address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
        or getattr(address, "is_site_local", False)
    )


def _resolve_public_fetch_addresses(host: str, port: int) -> tuple[str, ...]:
    normalized = host.strip().lower().strip("[]").rstrip(".")
    if not normalized:
        raise ValueError("Web fetch URL must include a valid hostname.")

    try:
        literal_address = ipaddress.ip_address(normalized)
    except ValueError:
        try:
            answers = socket.getaddrinfo(
                normalized,
                port,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            )
        except socket.gaierror as exc:
            raise ValueError(f"Web fetch DNS resolution failed for {normalized}: {exc}") from exc
        raw_addresses = [str(answer[4][0]).split("%", 1)[0] for answer in answers]
    else:
        raw_addresses = [str(literal_address)]

    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    seen: set[str] = set()
    for raw_address in raw_addresses:
        try:
            address = ipaddress.ip_address(raw_address)
        except ValueError as exc:
            raise ValueError(
                f"Web fetch DNS resolution returned an invalid address for {normalized}: "
                f"{raw_address}"
            ) from exc
        canonical_address = str(address)
        if canonical_address not in seen:
            addresses.append(address)
            seen.add(canonical_address)

    if not addresses:
        raise ValueError(f"Web fetch DNS resolution returned no addresses for {normalized}.")

    blocked_addresses = [
        str(address) for address in addresses if not _is_public_fetch_address(address)
    ]
    if blocked_addresses:
        raise ValueError(
            f"Web fetch host {normalized} resolved to non-public address(es): "
            f"{', '.join(blocked_addresses)}."
        )
    return tuple(str(address) for address in addresses)


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
