from __future__ import annotations

import json
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
) -> list[dict[str, Any]]:
    """Normalize web_search/web_fetch ToolMessage payloads into evidence dicts."""

    message_list = list(messages)
    call_names = _tool_call_names(message_list)
    items: list[EvidenceItem] = []
    for message in message_list:
        if not isinstance(message, ToolMessage):
            continue
        tool_name = _tool_name_for_message(message, call_names=call_names)
        if tool_name not in _WEB_EVIDENCE_TOOLS:
            continue
        payload = _json_payload(message)
        if not isinstance(payload, dict):
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
) -> list[dict[str, Any]]:
    """Normalize web evidence and attach stable per-turn ledger metadata."""

    message_list = list(messages)
    call_names = _tool_call_names(message_list)
    ledger: list[dict[str, Any]] = []
    for message in message_list:
        if not isinstance(message, ToolMessage):
            continue
        tool_call_id = str(message.tool_call_id or "").strip()
        tool_name = _tool_name_for_message(message, call_names=call_names)
        if tool_name not in _WEB_EVIDENCE_TOOLS:
            continue
        payload = _json_payload(message)
        if not isinstance(payload, dict) or _tool_message_status(message, payload) == "error":
            continue
        if tool_name == "web_search":
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
        return []
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
]
