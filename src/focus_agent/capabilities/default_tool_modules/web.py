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
    _binary_payload_kind,
    _head_tail_text_window,
    _ReadableHTMLExtractor,
    _resolve_public_fetch_addresses,
    _web_fetch_policy_violation,
)
from .web_search_tool import build_web_search_runner
from .web_transport import request_pinned_fetch_url

_WEB_FETCH_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_WEB_FETCH_MAX_REDIRECTS = 5
_WEB_FETCH_MAX_BYTES = 8 * 1024 * 1024
_WEB_FETCH_TRUNCATION_MARKER = "\n\n[... middle omitted ...]\n\n"
_WEB_FETCH_MAX_OBSERVATION_CHARS = 7000
_WEB_FETCH_MIN_DISPLAY_CHARS = 200


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

    blocked_fetch_domains = tuple(getattr(tool_catalog.web_fetch, "blocked_domains", ()) or ())
    allowed_fetch_domains = tuple(getattr(tool_catalog.web_fetch, "allowed_domains", ()) or ())

    def _http() -> httpx.Client:
        return http_client or shared_sync_http_client()

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

    _run_web_search, _fallback_web_search = build_web_search_runner(
        web_search_config=web_search_config,
        resolved_env=resolved_env,
        emit_tool_event=emit_tool_event,
        http=_http,
    )

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
            observed_at = datetime.now(UTC).isoformat()
            saved_ref: list[str | None] = []

            def save_full_content() -> str | None:
                # Saved at most once, and only when the shown window omits text.
                if saved_ref:
                    return saved_ref[0]
                artifact_ref = None
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
                saved_ref.append(artifact_ref)
                return artifact_ref

            def build_payload(display_chars: int) -> dict[str, Any]:
                window_budget = (
                    display_chars
                    if len(content) <= display_chars
                    else max(1, display_chars - len(_WEB_FETCH_TRUNCATION_MARKER))
                )
                head, tail, truncated = _head_tail_text_window(content, window_budget)
                continuation: dict[str, Any] | None = None
                displayed_content = content
                if truncated:
                    displayed_content = f"{head}{_WEB_FETCH_TRUNCATION_MARKER}{tail}"
                    if display_chars <= len(_WEB_FETCH_TRUNCATION_MARKER):
                        head, tail = content[:display_chars], ""
                        displayed_content = head
                    artifact_ref = save_full_content()
                    if artifact_ref:
                        continuation = {
                            "artifact_ref": artifact_ref,
                            "tool": "artifact_read",
                            "args": {
                                "artifact_id": artifact_ref,
                                "offset": len(head),
                                "limit": display_chars,
                            },
                            "offset": len(head),
                            "limit": display_chars,
                            "total_chars": len(content),
                            "hint": (
                                "Call artifact_read using the supplied args "
                                "to page through the omitted middle."
                            ),
                        }
                    else:
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
                    "observed_at": observed_at,
                    "published_at": published_at,
                    "source_type": "page",
                }
                if continuation is not None:
                    payload["continuation"] = continuation
                    payload["total_chars"] = len(content)
                    if continuation.get("artifact_ref"):
                        payload["artifact_ref"] = continuation["artifact_ref"]
                        payload["next_offset"] = len(head)
                return payload

            # The observation is trimmed above _WEB_FETCH_MAX_OBSERVATION_CHARS, which
            # would hide text that the continuation offset already skips. Shrink the
            # shown window until the serialized payload fits, so nothing is lost.
            display_chars = capped_chars
            while True:
                payload = build_payload(display_chars)
                result = json.dumps(payload, ensure_ascii=False)
                overflow = len(result) - _WEB_FETCH_MAX_OBSERVATION_CHARS
                if overflow <= 0 or display_chars <= _WEB_FETCH_MIN_DISPLAY_CHARS:
                    break
                display_chars = max(_WEB_FETCH_MIN_DISPLAY_CHARS, display_chars - overflow - 64)
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
                "max_observation_chars": _WEB_FETCH_MAX_OBSERVATION_CHARS,
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
