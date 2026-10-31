from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .policy_temporal import requires_temporal_anchor

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
# Longest first so "帮我查吧" is removed before its "查吧" suffix.
_CJK_CARRYOVER_MARKERS = sorted(
    (marker for marker in _TOOL_CARRYOVER_CONFIRMATION_MARKERS if not marker.isascii()),
    key=len,
    reverse=True,
)
_CARRYOVER_NEGATIONS = ("不", "别", "没", "勿")
_CARRYOVER_FILLER_CHARS = frozenset("的啊吧呀呢嗯了哈呗请查搜一下")


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
    # Short CJK confirmations ("好的，帮我查吧") count only when nothing but markers and
    # filler particles remain; "不可以" or "可以解释一下…吗" are not consent.
    compact = re.sub(r"[\s,，。.!！?？;；:：]+", "", text.strip().lower())
    if not compact or any(negation in compact for negation in _CARRYOVER_NEGATIONS):
        return False
    residual = compact
    for marker in _CJK_CARRYOVER_MARKERS:
        residual = residual.replace(marker, "")
    return residual != compact and all(char in _CARRYOVER_FILLER_CHARS for char in residual)


def normalize_carryover_text(text: str) -> str:
    return re.sub(r"[\s,，。.!！?？;；:：]+", " ", text.strip().lower()).strip()


__all__ = [
    "first_mapping_text",
    "is_tool_carryover_confirmation",
    "normalize_carryover_text",
    "pending_live_web_search_intent",
    "requires_temporal_anchor",
]
