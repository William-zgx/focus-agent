"""Shared lexical patterns and term groups for graph intent classification.

Live-web intent marker sets in ``policy_markers`` are derived from the term
groups below so that the Chinese and English vocabularies, and the "is this a
live question" / "should it start with web_search" / "does it need fresh
external evidence" decisions, stay consistent.
"""

from __future__ import annotations

import re

HTTP_URL_RE = re.compile(r"https?://[^\s<>()\"'，。！？、]+", re.IGNORECASE)
CJK_CHAR_CLASS = "一-鿿"
CJK_RE = re.compile(f"[{CJK_CHAR_CLASS}]")


def contains_cjk(text: object) -> bool:
    """Return True when ``text`` contains at least one CJK unified ideograph."""

    return bool(CJK_RE.search(str(text or "")))


# Explicit requests to search the web.
WEB_SEARCH_ACTION_TERMS = ("查一下", "查下", "搜一下", "搜索", "browse", "search")
# Explicit requests to go online or open/read a page (fetch-oriented).
WEB_ACCESS_TERMS = (
    "联网",
    "上网",
    "打开",
    "读取",
    "网页",
    "页面",
    "网址",
    "链接",
    "fetch",
    "web",
    "url",
    "http://",
    "https://",
)
# Relative time windows that make an answer time-sensitive.
TIME_WINDOW_TERMS = (
    "最近",
    "近期",
    "今天",
    "明天",
    "昨天",
    "本周",
    "这周",
    "近一",
    "过去",
    "年内",
    "今年",
    "latest",
    "recent",
    "today",
    "tomorrow",
    "yesterday",
    "this week",
)
# Freshness words that ask for the newest state of something.
LATEST_STATE_TERMS = ("最新", "实时")
# Bare "current/now" words; ambiguous on their own (see _BARE_CURRENT_MARKERS).
CURRENT_TERMS = ("现在", "当前", "current", "now")
NEWS_TERMS = ("新闻", "news")
WEATHER_TERMS = ("天气", "气温", "降雨", "下雨", "预报")
WEATHER_INTENT_TERMS = (
    "天气",
    "气温",
    "降雨",
    "预报",
    "会下雨",
    "下雨吗",
    "weather",
    "forecast",
    "will it rain",
)
FX_TERMS = ("汇率", "美元", "人民币", "日元", "欧元")
MARKET_INDEX_TERMS = ("大盘", "沪指", "上证", "深证", "创业板")
MARKET_TERMS = (
    "价格",
    "汇率",
    "股价",
    "股票",
    "行情",
    "走势",
    "波动",
    "涨跌",
    "涨跌幅",
    "涨幅",
    "跌幅",
    "收盘价",
    "开盘价",
    "最高价",
    "最低价",
    "成交量",
    "龙头股",
    "个股",
    "板块",
    "a股",
    "港股",
    "美股",
    "财报",
    "基本面",
    "估值",
    "price",
    "exchange rate",
    "stock price",
    "share price",
)
# Popularity/ranking words. A bare "火" is excluded: it matches 火锅/火车/火灾.
POPULARITY_TERMS = (
    "热门",
    "比较火",
    "很火",
    "最火",
    "火爆",
    "流行",
    "榜单",
    "排行",
    "trending",
    "popular",
    "hot",
)
_LIVE_TOPIC_TERMS = (
    *TIME_WINDOW_TERMS,
    *NEWS_TERMS,
    *WEATHER_INTENT_TERMS,
    *MARKET_TERMS,
    *POPULARITY_TERMS,
)


def _unique(*groups: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(term for group in groups for term in group))


# Any signal that the question concerns the live web.
LIVE_WEB_INTENT_TERMS = _unique(
    WEB_SEARCH_ACTION_TERMS,
    WEB_ACCESS_TERMS,
    LATEST_STATE_TERMS,
    CURRENT_TERMS,
    _LIVE_TOPIC_TERMS,
)
# Signals that a live-web turn should start with web_search (not web_fetch).
LIVE_WEB_SEARCH_FIRST_TERMS = _unique(
    WEB_SEARCH_ACTION_TERMS, LATEST_STATE_TERMS, _LIVE_TOPIC_TERMS
)
# Signals that the answer needs fresh external evidence.
FRESH_EXTERNAL_INTENT_TERMS = _unique(LATEST_STATE_TERMS, CURRENT_TERMS, _LIVE_TOPIC_TERMS)


__all__ = [
    "CJK_CHAR_CLASS",
    "CJK_RE",
    "CURRENT_TERMS",
    "FRESH_EXTERNAL_INTENT_TERMS",
    "FX_TERMS",
    "HTTP_URL_RE",
    "LATEST_STATE_TERMS",
    "LIVE_WEB_INTENT_TERMS",
    "LIVE_WEB_SEARCH_FIRST_TERMS",
    "MARKET_INDEX_TERMS",
    "MARKET_TERMS",
    "NEWS_TERMS",
    "POPULARITY_TERMS",
    "TIME_WINDOW_TERMS",
    "WEATHER_INTENT_TERMS",
    "WEATHER_TERMS",
    "WEB_ACCESS_TERMS",
    "WEB_SEARCH_ACTION_TERMS",
    "contains_cjk",
]
