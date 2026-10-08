import pytest

from focus_agent.engine.graph import policy_intent, policy_temporal
from focus_agent.engine.graph.policy_temporal import _temporal_live_web_search_args


@pytest.mark.parametrize(
    ("query", "days"),
    [
        ("过去3周的新闻", 21),
        ("近两个月 Agent 领域的进展", 60),
        ("这十天的天气预报", 10),
        ("last 2 months of agent research", 60),
        ("recent ten days of product news", 10),
        ("previous twelve months of market data", 360),
    ],
)
def test_explicit_windows_are_temporal_anchors(query: str, days: int) -> None:
    assert policy_temporal.explicit_window_days(query) == days
    assert policy_temporal.requires_temporal_anchor(query)
    assert policy_intent.requires_temporal_anchor(query)


def test_intent_import_keeps_the_single_temporal_predicate() -> None:
    assert policy_intent.requires_temporal_anchor is policy_temporal.requires_temporal_anchor


@pytest.mark.parametrize(
    ("query", "start_date"),
    [
        ("过去3周的新闻", "2026-09-18"),
        ("近两个月 Agent 领域的进展", "2026-08-10"),
        ("last 2 months of agent research", "2026-08-10"),
    ],
)
def test_explicit_windows_are_used_when_anchoring_search_queries(
    query: str, start_date: str
) -> None:
    args = _temporal_live_web_search_args(
        {"query": query},
        fallback_query="",
        current_utc_time="2026-10-08T03:00:00Z",
    )

    assert start_date in args["query"]
    assert "2026-10-08" in args["query"]


@pytest.mark.parametrize(
    "query",
    [
        "今天北京的天气怎么样？",
        "Please find the latest AI news.",
        "分析 Python 的列表排序实现",
        "解释 datetime.timedelta 的用法",
        "整理月度财报中的收入变化",
    ],
)
def test_temporal_detection_distinguishes_relative_time_from_plain_text(query: str) -> None:
    expected = query.startswith("今天") or "latest" in query.lower()
    assert policy_temporal.requires_temporal_anchor(query) is expected
