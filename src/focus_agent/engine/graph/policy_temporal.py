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
    return _rewrite_temporal_search_query(
        normalized_query,
        date_parts=date_parts,
        location_scope=location_scope,
    )


def _rewrite_temporal_search_query(
    query: str,
    *,
    date_parts: list[str],
    location_scope: str,
) -> str:
    date_tokens = _absolute_date_tokens(date_parts)
    if not date_tokens:
        return query
    semantic_terms = _semantic_search_terms(query, location_scope=location_scope)
    rewritten = " ".join(dict.fromkeys([*date_tokens, *semantic_terms]))
    return rewritten.strip() or query


def _absolute_date_tokens(date_parts: list[str]) -> list[str]:
    tokens: list[str] = []
    for part in date_parts:
        tokens.extend(re.findall(r"\d{4}-\d{2}-\d{2}", part))
    return tokens


def _semantic_search_terms(query: str, *, location_scope: str) -> list[str]:
    if re.search(r"[\u4e00-\u9fff]", query):
        return _chinese_semantic_search_terms(query, location_scope=location_scope)
    return _english_semantic_search_terms(query, location_scope=location_scope)


def _chinese_semantic_search_terms(query: str, *, location_scope: str) -> list[str]:
    terms: list[str] = []
    if location_scope:
        terms.append(location_scope)
    domain_term_count = 0

    if _contains_any(query, ("国家大事", "国内大事", "重大事件", "重大新闻")):
        if not location_scope and not _contains_any(
            query, ("全球", "国际", "美国", "台湾", "香港")
        ):
            terms.append("中国")
        terms.extend(["国家大事", "重大新闻"])
        domain_term_count += 2
    elif _contains_any(query, ("新闻", "大事", "事件", "发生")):
        terms.append("新闻")
        domain_term_count += 1

    if _contains_any(query, ("天气", "气温", "降雨", "下雨", "预报")):
        terms.append("天气")
        domain_term_count += 1
    if _contains_any(query, ("股价", "股票", "行情", "走势", "波动", "大盘", "沪指", "A股")):
        if _contains_any(query, ("A股", "大盘", "沪指", "上证", "深证", "创业板")):
            terms.extend(["A股", "大盘", "表现"])
            domain_term_count += 3
        else:
            terms.extend(["股价", "行情"])
            domain_term_count += 2
    if _contains_any(query, ("汇率", "美元", "人民币", "日元", "欧元")):
        terms.append("汇率")
        domain_term_count += 1

    fallback = _strip_chinese_search_filler(query)
    if fallback and domain_term_count == 0:
        terms.extend(fallback.split())
    return [term for term in terms if term]


def _english_semantic_search_terms(query: str, *, location_scope: str) -> list[str]:
    lowered = query.lower()
    terms: list[str] = []
    if location_scope:
        terms.append(location_scope)
    domain_term_count = 0
    if re.search(r"\b(?:major|national|country|state)\b", lowered) and re.search(
        r"\b(?:event|events|news|happened|happen)\b",
        lowered,
    ):
        terms.extend(["major national events", "news"])
        domain_term_count += 2
    elif re.search(r"\b(?:news|events?|happened|happen)\b", lowered):
        terms.append("news")
        domain_term_count += 1
    if re.search(r"\b(?:weather|temperature|forecast|rain|snow)\b", lowered):
        terms.append("weather")
        domain_term_count += 1
    if re.search(r"\b(?:stock|share price|market|index|nasdaq|dow|s&p|a-share)\b", lowered):
        terms.append("stock market")
        domain_term_count += 1
    fallback = _strip_english_search_filler(query)
    if fallback and domain_term_count == 0:
        terms.append(fallback)
    return [term for term in terms if term]


def _strip_chinese_search_filler(query: str) -> str:
    text = query
    text = re.sub(r"\d{4}[-年]\d{1,2}[-月]\d{1,2}日?", " ", text)
    text = re.sub(
        r"(?:今天|明天|昨天|本周|这周|近一周|最近一周|过去一周|最近|近期|当前|现在)", " ", text
    )
    text = re.sub(
        r"(?:帮我|请|麻烦|查一下|查下|搜一下|搜索|看一下|看看|告诉我|列出|给我|一下)", " ", text
    )
    text = re.sub(
        r"(?:有什么|有哪些|哪个|哪些|如何|怎么样|是否|能否|可以|具体|结果|来源|发生|吗|呢)",
        " ",
        text,
    )
    text = re.sub(r"[，。！？、,.?!（）()；;:：\"'“”‘’]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= 1:
        return ""
    return text[:80]


def _strip_english_search_filler(query: str) -> str:
    text = query.lower()
    text = re.sub(
        r"\b(?:today|tomorrow|yesterday|current|now|this week|last 7 days|past week)\b", " ", text
    )
    text = re.sub(
        r"\b(?:what|which|please|can you|could you|help me|search|look up|find|tell me|list|show|give|from search results|concrete items?|happened|happen)\b",
        " ",
        text,
    )
    text = re.sub(r"[^a-z0-9 .'-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:100]


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
        parts.append(
            f"绝对时间范围(近一周/UTC)：{window_start.isoformat()} 至 {anchor_date.isoformat()}"
        )
    return list(dict.fromkeys(parts))


def _extract_location_or_scope(query: str) -> str:
    patterns = (
        r"(?:今天|明天|昨天|本周|这周|近一周|最近一周|过去一周|最近|近期)\s*([\u4e00-\u9fffA-Za-z][\w\u4e00-\u9fff\s·.-]{1,24}?)(?:天气|新闻|股价|股票|行情|汇率|走势|波动|访问)",
        r"([\u4e00-\u9fff]{2,12})(?:今天|明天|昨天|本周|这周|近一周|最近|近期).{0,12}(?:天气|新闻|股价|股票|行情|汇率|走势|波动|访问)",
        r"(?:访问|到访|访华)([\u4e00-\u9fff]{2,12})",
        r"(?i)\b([a-z][a-z .'-]{1,40}?)\s+(?:weather|forecast|temperature|news|stock|price)\b",
        r"(?i)\b(?:in|for|at)\s+([a-z][a-z .'-]{1,40}?)(?:\s+(?:today|tomorrow|this week|weather|news|stock|price|list|show|give|include|from|with)|[?.!,]|$)",
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
    cleaned = re.sub(
        r"(?i)\s+\b(?:list|show|give|include|from|with|and|concrete|items?|results?|sources?|search)\b.*$",
        "",
        cleaned,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ，。,.?!？")
    return cleaned[:40]
