from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from .policy_intent import requires_temporal_anchor as _requires_temporal_anchor
from .policy_markers import _contains_any


def _temporal_live_web_search_args(
    preferred_args: Mapping[str, Any] | None,
    *,
    fallback_query: str,
    current_utc_time: str | None,
) -> dict[str, Any]:
    base_query = ""
    if isinstance(preferred_args, Mapping):
        base_query = str(preferred_args.get("query") or "").strip()
    if not base_query:
        base_query = str(fallback_query or "").strip()
    if not base_query:
        return {}
    if not current_utc_time or not _requires_temporal_anchor(base_query):
        return {"query": base_query}
    anchored_query = _anchor_relative_time_query(base_query, current_utc_time)
    return {"query": anchored_query or base_query}


def _anchor_relative_time_query(query: str, current_utc_time: str) -> str:
    normalized_query = " ".join(str(query or "").strip().split())
    if not normalized_query or "原始查询：" in normalized_query:
        return normalized_query
    anchor = _parse_current_utc_time(current_utc_time)
    if anchor is None:
        return normalized_query
    date_parts = _relative_date_parts(normalized_query, anchor)
    if not date_parts:
        return normalized_query
    location_scope = _extract_location_or_scope(normalized_query)
    metadata = [
        f"原始查询：{normalized_query}",
        f"当前UTC时间：{anchor.isoformat().replace('+00:00', 'Z')}",
        *date_parts,
    ]
    if location_scope:
        metadata.append(f"地点/范围：{location_scope}")
    else:
        metadata.append("地点/范围：见原始查询")
    return f"{normalized_query}（{'; '.join(metadata)}）"


def _parse_current_utc_time(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    candidate = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        match = re.search(r"\d{4}-\d{2}-\d{2}(?:[T ][0-9:.+-]+)?", text)
        if not match:
            return None
        try:
            parsed = datetime.fromisoformat(match.group(0).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _relative_date_parts(query: str, anchor: datetime) -> list[str]:
    lowered = query.lower()
    anchor_date = anchor.date()
    parts: list[str] = []
    if _contains_any(query, ("今天", "today", "现在", "当前", "current", "now")):
        parts.append(f"绝对日期(今天/UTC)：{anchor_date.isoformat()}")
    if _contains_any(query, ("明天", "tomorrow")):
        parts.append(f"绝对日期(明天/UTC)：{(anchor_date + timedelta(days=1)).isoformat()}")
    if _contains_any(query, ("昨天", "yesterday")):
        parts.append(f"绝对日期(昨天/UTC)：{(anchor_date - timedelta(days=1)).isoformat()}")
    if _contains_any(query, ("本周", "这周", "this week")):
        week_start = anchor_date - timedelta(days=anchor_date.weekday())
        week_end = week_start + timedelta(days=6)
        parts.append(f"绝对时间范围(本周/UTC)：{week_start.isoformat()} 至 {week_end.isoformat()}")
    if _contains_any(
        query,
        ("近一周", "最近一周", "过去一周", "last 7 days", "past week"),
    ) or re.search(r"(?<![a-z0-9_])recent(?:ly)?(?![a-z0-9_])", lowered):
        window_start = anchor_date - timedelta(days=6)
        parts.append(f"绝对时间范围(近一周/UTC)：{window_start.isoformat()} 至 {anchor_date.isoformat()}")
    return list(dict.fromkeys(parts))


def _extract_location_or_scope(query: str) -> str:
    patterns = (
        r"(?:今天|明天|昨天|本周|这周|近一周|最近一周|过去一周|最近|近期)\s*([\u4e00-\u9fffA-Za-z][\w\u4e00-\u9fff\s·.-]{1,24}?)(?:天气|新闻|股价|股票|行情|汇率|走势|波动|访问)",
        r"([\u4e00-\u9fff]{2,12})(?:今天|明天|昨天|本周|这周|近一周|最近|近期).{0,12}(?:天气|新闻|股价|股票|行情|汇率|走势|波动|访问)",
        r"(?:访问|到访|访华)([\u4e00-\u9fff]{2,12})",
        r"(?i)\b(?:in|for|at)\s+([a-z][a-z .'-]{1,40}?)(?:\s+(?:today|tomorrow|this week|weather|news|stock|price)|[?.!,]|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, query)
        if not match:
            continue
        value = _clean_location_scope(match.group(1))
        if value:
            return value
    return ""


def _clean_location_scope(value: str) -> str:
    cleaned = re.sub(
        r"^(?:帮我|请|查一下|查下|搜一下|搜索|看一下|看看|一下|有哪个|哪个|哪些|the)\s*",
        "",
        str(value or "").strip(),
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ，。,.?!？")
    return cleaned[:40]
