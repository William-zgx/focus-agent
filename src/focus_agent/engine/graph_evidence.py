from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from langchain.messages import AIMessage, ToolMessage

TrustTier = str

TRUST_TIER_HIGH: TrustTier = "high"
TRUST_TIER_MEDIUM: TrustTier = "medium"
TRUST_TIER_BACKGROUND: TrustTier = "background"
TRUST_TIER_LOW: TrustTier = "low"

_WEB_EVIDENCE_TOOLS = {"web_search", "web_fetch"}

_HIGH_TRUST_DOMAINS = {
    "china-embassy.gov.cn",
    "europa.eu",
    "ec.europa.eu",
    "imf.org",
    "mfa.gov.cn",
    "mod.gov.cn",
    "oecd.org",
    "un.org",
    "www.gov.cn",
    "who.int",
    "worldbank.org",
}

_RECOGNIZED_NEWS_DOMAINS = {
    "aljazeera.com",
    "apnews.com",
    "bbc.com",
    "bloomberg.com",
    "cnbc.com",
    "economist.com",
    "ft.com",
    "guardian.com",
    "globaltimes.cn",
    "npr.org",
    "nytimes.com",
    "news.cn",
    "people.com.cn",
    "reuters.com",
    "theguardian.com",
    "wsj.com",
    "washingtonpost.com",
}

_WEATHER_BACKGROUND_DOMAINS = {
    "accuweather.com",
    "timeanddate.com",
    "weather.com",
    "weatherbase.com",
    "wunderground.com",
}

_PUBLISHED_AT_KEYS = (
    "published_at",
    "published",
    "published_date",
    "publishedDate",
    "date",
    "last_updated",
    "updated_at",
)


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    source_name: str
    url: str
    title: str
    snippet: str
    trust_tier: TrustTier
    published_at: str | None = None
    observed_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source_name": self.source_name,
            "url": self.url,
            "title": self.title,
            "snippet": self.snippet,
            "trust_tier": self.trust_tier,
        }
        if self.published_at:
            payload["published_at"] = self.published_at
        else:
            payload["observed_at"] = self.observed_at or _now_iso()
        return payload


def normalize_evidence_bundle(
    messages: Iterable[Any],
    *,
    observed_at: str | None = None,
    user_query: str | None = None,
) -> list[dict[str, Any]]:
    """Normalize web_search/web_fetch ToolMessage payloads into evidence dicts."""

    message_list = list(messages)
    call_names = _tool_call_names(message_list)
    relevant_call_ids = relevant_web_tool_call_ids(message_list, user_query=user_query)
    items: list[EvidenceItem] = []
    for message in message_list:
        if not isinstance(message, ToolMessage):
            continue
        tool_call_id = _clean_text(getattr(message, "tool_call_id", ""))
        if relevant_call_ids is not None and tool_call_id not in relevant_call_ids:
            continue
        tool_name = _tool_name_for_message(message, call_names=call_names)
        if tool_name not in _WEB_EVIDENCE_TOOLS:
            continue
        payload = _json_payload(message)
        if not isinstance(payload, dict):
            item = _raw_payload_item(
                tool_name=tool_name,
                message=message,
                observed_at=observed_at,
            )
            if item is not None:
                items.append(item)
            continue
        if _tool_message_status(message, payload) == "error":
            continue
        if tool_name == "web_search":
            items.extend(_search_payload_items(payload, observed_at=observed_at))
        elif tool_name == "web_fetch":
            item = _fetch_payload_item(payload, observed_at=observed_at)
            if item is not None:
                items.append(item)
    return [item.as_dict() for item in _dedupe_items(items)]


def normalize_evidence_ledger(
    messages: Iterable[Any],
    *,
    observed_at: str | None = None,
    user_query: str | None = None,
) -> list[dict[str, Any]]:
    """Normalize web evidence and attach stable per-turn ledger metadata."""

    message_list = list(messages)
    call_names = _tool_call_names(message_list)
    relevant_call_ids = relevant_web_tool_call_ids(message_list, user_query=user_query)
    ledger: list[dict[str, Any]] = []
    for message in message_list:
        if not isinstance(message, ToolMessage):
            continue
        tool_call_id = str(message.tool_call_id or "").strip()
        if relevant_call_ids is not None and tool_call_id not in relevant_call_ids:
            continue
        tool_name = _tool_name_for_message(message, call_names=call_names)
        if tool_name not in _WEB_EVIDENCE_TOOLS:
            continue
        payload = _json_payload(message)
        if not isinstance(payload, dict):
            item = _raw_payload_item(
                tool_name=tool_name,
                message=message,
                observed_at=observed_at,
            )
            items = [item] if item is not None else []
        elif _tool_message_status(message, payload) == "error":
            continue
        elif tool_name == "web_search":
            items = _search_payload_items(payload, observed_at=observed_at)
        else:
            item = _fetch_payload_item(payload, observed_at=observed_at)
            items = [item] if item is not None else []
        for item in items:
            ledger.append(
                {
                    **item.as_dict(),
                    "id": f"ev-{len(ledger) + 1}",
                    "source_tool": tool_name,
                    "tool_call_id": tool_call_id,
                }
            )
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in ledger:
        key = (
            _clean_text(item.get("url")),
            _clean_text(item.get("title")),
            _clean_text(item.get("snippet")),
        )
        if key in seen:
            continue
        seen.add(key)
        item["id"] = f"ev-{len(deduped) + 1}"
        deduped.append(item)
    return deduped


def relevant_web_tool_call_ids(
    messages: Iterable[Any],
    *,
    user_query: str | None = None,
) -> set[str] | None:
    query_terms = _query_relevance_terms(user_query or "")
    if not query_terms:
        return None
    message_list = list(messages)
    call_names = _tool_call_names(message_list)
    call_text_by_id = _tool_call_text_by_id(message_list)
    web_messages: list[tuple[str, str]] = []
    for message in message_list:
        if not isinstance(message, ToolMessage):
            continue
        tool_call_id = _clean_text(getattr(message, "tool_call_id", ""))
        tool_name = _tool_name_for_message(message, call_names=call_names)
        if tool_call_id and tool_name in _WEB_EVIDENCE_TOOLS:
            payload = _json_payload(message)
            haystack = " ".join(
                part
                for part in (
                    call_text_by_id.get(tool_call_id, ""),
                    _payload_relevance_text(payload),
                    _clean_text(getattr(message, "content", ""), max_chars=1000),
                )
                if part
            )
            web_messages.append((tool_call_id, haystack))
    if len(web_messages) <= 1:
        return {tool_call_id for tool_call_id, _haystack in web_messages}
    relevant: set[str] = set()
    for tool_call_id, haystack in web_messages:
        if _matches_query_terms(haystack, query_terms):
            relevant.add(tool_call_id)
    return relevant


def evidence_bundle_to_citation_refs(
    evidence_bundle: Iterable[dict[str, Any]],
    *,
    limit: int = 10,
) -> list[dict[str, str | None]]:
    if limit <= 0:
        return []
    citations: list[dict[str, str | None]] = []
    for item in evidence_bundle:
        if not isinstance(item, dict):
            continue
        url = _clean_text(item.get("url"))
        label = _clean_text(item.get("title")) or _clean_text(item.get("source_name")) or url
        if not label:
            continue
        citations.append(
            {
                "label": label,
                "uri": url or None,
                "quote": _clean_text(item.get("snippet")) or None,
                "source_artifact_id": None,
            }
        )
        if len(citations) >= limit:
            break
    return citations


def evidence_bundle_source_snippets(
    evidence_bundle: Iterable[dict[str, Any]],
    *,
    limit: int = 8,
    include_background: bool = True,
) -> list[str]:
    if limit <= 0:
        return []
    snippets: list[str] = []
    for item in evidence_bundle:
        if not isinstance(item, dict):
            continue
        tier = _clean_text(item.get("trust_tier")) or TRUST_TIER_LOW
        if tier == TRUST_TIER_BACKGROUND and not include_background:
            continue
        source_name = _clean_text(item.get("source_name"))
        title = _clean_text(item.get("title"))
        url = _clean_text(item.get("url"))
        snippet = _clean_text(item.get("snippet"), max_chars=220)
        if not (source_name or title or url or snippet):
            continue
        label = " - ".join(part for part in (source_name, title) if part)
        body = " ".join(part for part in (label, snippet) if part)
        if url:
            body = f"{body} ({url})" if body else url
        snippets.append(f"- Evidence [{tier}]: {body}")
        if len(snippets) >= limit:
            break
    return snippets


def _search_payload_items(
    payload: dict[str, Any], *, observed_at: str | None
) -> list[EvidenceItem]:
    results = payload.get("results")
    if not isinstance(results, list):
        return _search_summary_items(payload, observed_at=observed_at)
    if not results:
        return _search_summary_items(payload, observed_at=observed_at)
    items: list[EvidenceItem] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        url = _clean_text(result.get("url") or result.get("ref"))
        title = _clean_text(result.get("title"))
        snippet = _clean_text(result.get("content") or result.get("snippet"))
        source_name = _source_name(result, url=url)
        published_at = _published_at(result)
        items.append(
            EvidenceItem(
                source_name=source_name,
                url=url,
                title=title,
                snippet=snippet,
                trust_tier=_trust_tier(
                    source_name=source_name,
                    url=url,
                    title=title,
                    snippet=snippet,
                ),
                published_at=published_at,
                observed_at=None if published_at else observed_at,
            )
        )
    return items


def _search_summary_items(
    payload: dict[str, Any], *, observed_at: str | None
) -> list[EvidenceItem]:
    snippet = _clean_text(
        payload.get("answer") or payload.get("summary") or payload.get("reference")
    )
    if not snippet:
        return []
    title = _clean_text(payload.get("query")) or "web_search result"
    source_name = _source_name(payload, url=_clean_text(payload.get("url") or ""))
    return [
        EvidenceItem(
            source_name=source_name or "web_search",
            url=_clean_text(payload.get("url")),
            title=title,
            snippet=snippet,
            trust_tier=TRUST_TIER_LOW,
            published_at=_published_at(payload),
            observed_at=observed_at,
        )
    ]


def _raw_payload_item(
    *,
    tool_name: str,
    message: ToolMessage,
    observed_at: str | None,
) -> EvidenceItem | None:
    raw = _clean_text(getattr(message, "content", ""), max_chars=1000)
    if not raw:
        return None
    return EvidenceItem(
        source_name=tool_name or "web",
        url="",
        title=f"{tool_name or 'web'} result",
        snippet=raw,
        trust_tier=TRUST_TIER_LOW,
        observed_at=observed_at,
    )


def _fetch_payload_item(payload: dict[str, Any], *, observed_at: str | None) -> EvidenceItem | None:
    url = _clean_text(payload.get("final_url") or payload.get("url"))
    title = _clean_text(payload.get("title"))
    snippet = _clean_text(payload.get("content") or payload.get("text") or payload.get("summary"))
    if not (url or title or snippet):
        return None
    source_name = _source_name(payload, url=url)
    published_at = _published_at(payload)
    return EvidenceItem(
        source_name=source_name,
        url=url,
        title=title,
        snippet=snippet,
        trust_tier=_trust_tier(
            source_name=source_name,
            url=url,
            title=title,
            snippet=snippet,
        ),
        published_at=published_at,
        observed_at=None if published_at else observed_at,
    )


def _trust_tier(*, source_name: str, url: str, title: str, snippet: str) -> TrustTier:
    if not snippet:
        return TRUST_TIER_LOW
    host = _normalized_host(url)
    haystack = " ".join([host, source_name, url, title, snippet]).lower()
    if _is_weather_or_monthly_climate(host=host, haystack=haystack):
        return TRUST_TIER_BACKGROUND
    if _is_official_or_government(host=host, source_name=source_name):
        return TRUST_TIER_HIGH
    if _domain_matches(host, _RECOGNIZED_NEWS_DOMAINS):
        return TRUST_TIER_MEDIUM
    return TRUST_TIER_LOW


def _is_weather_or_monthly_climate(*, host: str, haystack: str) -> bool:
    if _domain_matches(host, _WEATHER_BACKGROUND_DOMAINS):
        return True
    return (
        "monthly" in haystack or "climate" in haystack or "average weather" in haystack
    ) and "weather" in haystack


def _is_official_or_government(*, host: str, source_name: str) -> bool:
    if not host:
        return False
    if host.endswith(".gov") or ".gov." in host or host.endswith(".mil"):
        return True
    if _domain_matches(host, _HIGH_TRUST_DOMAINS):
        return True
    return "official" in source_name.lower()


def _domain_matches(host: str, domains: set[str]) -> bool:
    if not host:
        return False
    return any(host == domain or host.endswith(f".{domain}") for domain in domains)


def _tool_call_names(messages: Iterable[Any]) -> dict[str, str]:
    call_names: dict[str, str] = {}
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        for call in getattr(message, "tool_calls", None) or []:
            if not isinstance(call, dict):
                continue
            call_id = _clean_text(call.get("id"))
            call_name = _clean_text(call.get("name"))
            if call_id and call_name:
                call_names[call_id] = call_name
    return call_names


def _tool_call_text_by_id(messages: Iterable[Any]) -> dict[str, str]:
    call_text: dict[str, str] = {}
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        for call in getattr(message, "tool_calls", None) or []:
            if not isinstance(call, dict):
                continue
            call_id = _clean_text(call.get("id"))
            if not call_id:
                continue
            args = call.get("args")
            parts = [_clean_text(call.get("name"))]
            if isinstance(args, dict):
                parts.extend(_clean_text(value) for value in args.values() if value)
            elif args:
                parts.append(_clean_text(args))
            call_text[call_id] = " ".join(part for part in parts if part)
    return call_text


def _tool_name_for_message(message: ToolMessage, *, call_names: dict[str, str]) -> str:
    artifact = getattr(message, "artifact", None)
    if isinstance(artifact, dict):
        tool_name = artifact.get("tool_name")
        if isinstance(tool_name, str) and tool_name.strip():
            return tool_name.strip()
        tool_payload = artifact.get("tool")
        if isinstance(tool_payload, dict) and isinstance(tool_payload.get("name"), str):
            return str(tool_payload["name"]).strip()
    call_id = _clean_text(getattr(message, "tool_call_id", ""))
    if call_id in call_names:
        return call_names[call_id]
    payload = _json_payload(message)
    if isinstance(payload, dict):
        tool_name = _clean_text(payload.get("tool"))
        if tool_name in _WEB_EVIDENCE_TOOLS:
            return tool_name
        if isinstance(payload.get("results"), list) and (
            payload.get("provider") or payload.get("query")
        ):
            return "web_search"
        if "content" in payload and (payload.get("url") or payload.get("final_url")):
            return "web_fetch"
    return ""


def _payload_relevance_text(payload: Any) -> str:
    if isinstance(payload, dict):
        parts: list[str] = []
        for key in ("query", "answer", "summary", "reference", "url", "final_url", "title"):
            value = payload.get(key)
            if value:
                parts.append(_clean_text(value, max_chars=1000))
        results = payload.get("results")
        if isinstance(results, list):
            for result in results:
                if not isinstance(result, dict):
                    continue
                for key in ("title", "url", "ref", "content", "snippet", "source_name", "source"):
                    value = result.get(key)
                    if value:
                        parts.append(_clean_text(value, max_chars=1000))
        return " ".join(parts)
    if isinstance(payload, list):
        return " ".join(_payload_relevance_text(item) for item in payload)
    return _clean_text(payload, max_chars=1000)


_QUERY_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "about",
    "please",
    "search",
    "latest",
    "recent",
    "today",
    "tomorrow",
    "yesterday",
    "this",
    "week",
    "current",
    "now",
}

_CJK_QUERY_STOP_PHRASES = (
    "帮我",
    "请",
    "查一下",
    "查下",
    "搜一下",
    "搜索",
    "看一下",
    "看看",
    "一下",
    "今天",
    "明天",
    "昨天",
    "本周",
    "这周",
    "近一周",
    "最近一周",
    "过去一周",
    "最近",
    "近期",
    "当前",
    "现在",
    "哪个",
    "哪些",
    "什么",
    "如何",
    "多少",
    "有没有",
    "有",
    "的",
)


def _query_relevance_terms(query: str) -> set[str]:
    text = _clean_text(query, max_chars=1200).lower()
    terms = {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9_+-]{1,}", text)
        if token not in _QUERY_STOPWORDS and len(token) >= 2
    }
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", query):
        cleaned = chunk
        for phrase in _CJK_QUERY_STOP_PHRASES:
            cleaned = cleaned.replace(phrase, "")
        cleaned = cleaned.strip()
        if len(cleaned) >= 2:
            terms.add(cleaned.lower())
            if len(cleaned) <= 12:
                terms.update(cleaned[index : index + 2].lower() for index in range(len(cleaned) - 1))
    return terms


def _matches_query_terms(text: str, query_terms: set[str]) -> bool:
    haystack = _clean_text(text, max_chars=5000).lower()
    if not haystack:
        return False
    return any(term and term in haystack for term in query_terms)


def _tool_message_status(message: ToolMessage, payload: dict[str, Any]) -> str:
    status = _clean_text(getattr(message, "status", "")) or _clean_text(payload.get("status"))
    return status.lower() or "success"


def _json_payload(message: ToolMessage) -> Any:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return None
    return content if isinstance(content, (dict, list)) else None


def _source_name(payload: dict[str, Any], *, url: str) -> str:
    source = _clean_text(payload.get("source_name") or payload.get("source") or payload.get("site"))
    return source or _normalized_host(url)


def _published_at(payload: dict[str, Any]) -> str | None:
    for key in _PUBLISHED_AT_KEYS:
        value = _clean_text(payload.get(key))
        if value:
            return value
    return None


def _normalized_host(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def _clean_text(value: Any, *, max_chars: int = 500) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 1]}…"


def _dedupe_items(items: Iterable[EvidenceItem]) -> list[EvidenceItem]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[EvidenceItem] = []
    for item in items:
        key = (item.url, item.title, item.snippet)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "EvidenceItem",
    "TRUST_TIER_BACKGROUND",
    "TRUST_TIER_HIGH",
    "TRUST_TIER_LOW",
    "TRUST_TIER_MEDIUM",
    "evidence_bundle_source_snippets",
    "evidence_bundle_to_citation_refs",
    "normalize_evidence_bundle",
    "normalize_evidence_ledger",
    "relevant_web_tool_call_ids",
]
