from __future__ import annotations

from html.parser import HTMLParser
import ipaddress
import json
from typing import Any, Callable
from urllib import error as stdlib_urllib_error
from urllib import parse as stdlib_urllib_parse
from urllib import request as stdlib_urllib_request

from langchain.tools import tool

from .common import _collapse_whitespace, _require_non_empty_text_arg


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

    def _run_tavily_search(*, query: str, max_results: int) -> dict[str, Any]:
        if not tavily_api_key:
            raise RuntimeError("TAVILY_API_KEY is not configured.")
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
            raise RuntimeError(f"Tavily search failed with HTTP {exc.code}: {body[:300]}") from exc
        except urllib_error_module.URLError as exc:
            raise RuntimeError(f"Tavily search failed: {exc.reason}") from exc
        except OSError as exc:
            raise RuntimeError(f"Tavily search failed: {exc}") from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Tavily search returned invalid JSON.") from exc

        results = data.get("results")
        if not isinstance(results, list):
            raise RuntimeError("Tavily search returned an unusable payload.")

        return {
            "query": query,
            "provider": "tavily",
            "answer": data.get("answer"),
            "results": [
                _normalize_search_result(
                    title=item.get("title"),
                    url=item.get("url"),
                    content=item.get("content"),
                )
                for item in results[:max_results]
            ],
        }

    def _run_duckduckgo_search(*, query: str, max_results: int) -> dict[str, Any]:
        try:
            from ddgs import DDGS
        except ImportError as exc:
            raise RuntimeError("DuckDuckGo fallback is unavailable because 'ddgs' is not installed.") from exc

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
            raise RuntimeError(f"DuckDuckGo search failed: {exc}") from exc

        return {
            "query": query,
            "provider": "duckduckgo",
            "answer": None,
            "results": [
                _normalize_search_result(
                    title=item.get("title"),
                    url=item.get("href") or item.get("link"),
                    content=item.get("body") or item.get("snippet"),
                )
                for item in raw_results[:max_results]
            ],
        }

    def _run_web_search_primary(*, query: str, max_results: int, tool_name: str) -> str:
        normalized_query = query.strip()
        capped_results = max(1, min(int(max_results), 10))
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

        should_try_tavily = preferred_web_search_provider in {"auto", "tavily"}
        if should_try_tavily and tavily_api_key:
            payload = _run_tavily_search(query=normalized_query, max_results=capped_results)
            result = json.dumps(payload, ensure_ascii=False)
            emit_tool_event(
                tool_name=tool_name,
                stage="end",
                provider=payload["provider"],
                result_count=len(payload["results"]),
                output=result[:800],
            )
            return result

        if should_try_tavily and not tavily_api_key:
            message = "Tavily search is configured but the API key is missing."
            emit_tool_event(tool_name=tool_name, stage="error", error=message, provider="tavily")
            raise RuntimeError(message)

        if preferred_web_search_provider == "duckduckgo":
            payload = _run_duckduckgo_search(query=normalized_query, max_results=capped_results)
            result = json.dumps(payload, ensure_ascii=False)
            emit_tool_event(
                tool_name=tool_name,
                stage="end",
                provider=payload["provider"],
                result_count=len(payload["results"]),
                output=result[:800],
            )
            return result

        message = "No primary web search provider is configured."
        emit_tool_event(tool_name=tool_name, stage="error", error=message)
        raise RuntimeError(message)

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
        payload = _run_duckduckgo_search(query=normalized_query, max_results=capped_results)
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
            if _is_blocked_fetch_host(parsed.hostname):
                raise ValueError("Refusing to fetch localhost, private, reserved, or link-local hosts.")
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
        return _run_web_search_primary(query=query, max_results=requested_results, tool_name="web_search")

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
