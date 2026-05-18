from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_TOOL_CARRYOVER_CONFIRMATION_MARKERS = frozenset(
    {
        "允许",
        "好的",
        "好",
        "帮我查吧",
        "继续",
        "查吧",
        "可以",
        "行",
        "ok",
        "okay",
        "yes",
        "continue",
        "go ahead",
    }
)

_TEMPORAL_ANCHOR_MARKERS = (
    "今天",
    "明天",
    "昨天",
    "本周",
    "这周",
    "近一周",
    "最近",
    "近期",
    "过去一周",
    "现在",
    "当前",
    "today",
    "tomorrow",
    "yesterday",
    "this week",
    "recent",
    "recently",
    "last 7 days",
    "past week",
    "now",
    "current",
)


def pending_live_web_search_intent(raw: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    policy = first_mapping_text(raw, ("policy", "tool_policy", "intent_policy"))
    tool_name = first_mapping_text(raw, ("preferred_first_tool", "tool", "tool_name", "name"))
    if policy != "live_web_research" or tool_name != "web_search":
        return None

    args = raw.get("preferred_first_args")
    if not isinstance(args, Mapping):
        args = raw.get("args")
    query = ""
    if isinstance(args, Mapping):
        query = str(args.get("query") or "").strip()
    if not query:
        query = first_mapping_text(raw, ("query", "normalized_text", "text"))
    if not query:
        return None
    return {"query": query}


def first_mapping_text(raw: Mapping[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = raw.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def is_tool_carryover_confirmation(text: str) -> bool:
    normalized = normalize_carryover_text(text)
    if normalized in _TOOL_CARRYOVER_CONFIRMATION_MARKERS:
        return True
    compact = re.sub(r"[\s,，。.!！?？;；:：]+", "", text.strip().lower())
    return any(
        marker in compact
        for marker in _TOOL_CARRYOVER_CONFIRMATION_MARKERS
        if len(marker) > 1 and not re.fullmatch(r"[a-z0-9]+(?:\s+[a-z0-9]+)*", marker)
    )


def normalize_carryover_text(text: str) -> str:
    return re.sub(r"[\s,，。.!！?？;；:：]+", " ", text.strip().lower()).strip()


def requires_temporal_anchor(text: str) -> bool:
    lowered = text.lower()
    return any(_marker_matches(lowered, marker) for marker in _TEMPORAL_ANCHOR_MARKERS)


def _marker_matches(lowered_text: str, marker: str) -> bool:
    normalized_marker = marker.strip().lower()
    if not normalized_marker:
        return False
    if re.fullmatch(r"[a-z0-9]+(?:\s+[a-z0-9]+)*", normalized_marker):
        pattern = (
            r"(?<![a-z0-9_])"
            + r"\s+".join(re.escape(part) for part in normalized_marker.split())
            + r"(?![a-z0-9_])"
        )
        return re.search(pattern, lowered_text) is not None
    return normalized_marker in lowered_text


__all__ = [
    "first_mapping_text",
    "is_tool_carryover_confirmation",
    "normalize_carryover_text",
    "pending_live_web_search_intent",
    "requires_temporal_anchor",
]
