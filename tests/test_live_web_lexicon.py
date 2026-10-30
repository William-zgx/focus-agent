"""Live-web marker sets are derived from shared lexicon groups.

These cases pin the intended classification after unifying the previously
divergent lists (see engine/graph/lexicon.py).
"""

from __future__ import annotations

import pytest

from focus_agent.engine.graph import lexicon, policy_markers
from focus_agent.engine.graph.policy import build_tool_intent_plan


def test_search_first_and_fresh_sets_are_subsets_of_live_intent_set() -> None:
    live = set(policy_markers._LIVE_WEB_INTENT_MARKERS)
    assert set(policy_markers._LIVE_WEB_SEARCH_FIRST_MARKERS) <= live
    assert set(policy_markers._FRESH_EXTERNAL_INTENT_MARKERS) <= live
    # Bare "current/now" alone never triggers search-first.
    assert not set(lexicon.CURRENT_TERMS) & set(policy_markers._LIVE_WEB_SEARCH_FIRST_MARKERS)


@pytest.mark.parametrize(
    "query",
    [
        # Unchanged: already started with web_search.
        "北京今天天气",
        "github 本周热门项目",
        "最近大模型排行榜",
        "上网查一下特斯拉股价",
        "latest news about OpenAI",
        "最近两个月 Agent 领域有什么进展",
        # Improved: these were live_web_research with no first tool (model had to
        # decide), or misclassified as direct answers.
        "美元兑人民币汇率是多少",
        "最新的 iPhone 型号是什么",
        "Python 最新版本是多少",
        "实时路况怎么样",
        "2026 年手机销量榜单",
        "current exchange rate USD to EUR",
        "上海会下雨吗",
        "北京气温多少度",
        "will it rain in Paris",
    ],
)
def test_live_questions_start_with_web_search(query: str) -> None:
    plan = build_tool_intent_plan(query)

    assert plan.policy == "live_web_research"
    assert plan.preferred_first_tool == "web_search"


@pytest.mark.parametrize(
    ("query", "policy"),
    [
        ("打开 https://example.com/post 读取内容", "live_web_research"),
        ("当前仓库里 build_graph 在哪里定义", "workspace_lookup"),
        ("当前代码有什么问题", "workspace_lookup"),
        ("现在几点", "direct_answer"),
        ("帮我写一首关于春天的诗", "direct_answer"),
        ("写一首关于下雨的诗", "direct_answer"),
        ("下雨天适合做什么", "direct_answer"),
        ("解释一下快速排序", "direct_answer"),
        # Improved: a bare "火" used to match 火锅/火车 and force a web search.
        ("火锅怎么做", "direct_answer"),
        ("火车票怎么买", "direct_answer"),
    ],
)
def test_non_live_or_fetch_questions_keep_their_policy(query: str, policy: str) -> None:
    plan = build_tool_intent_plan(query)

    assert plan.policy == policy
    assert plan.preferred_first_tool != "web_search"


def test_popularity_phrases_still_route_to_web_search() -> None:
    for query in ("抖音上很火的歌", "最近什么比较火", "现在什么最火", "这首歌很火吗"):
        assert build_tool_intent_plan(query).preferred_first_tool == "web_search", query


@pytest.mark.parametrize(
    "query",
    [
        "解释一下汇率是怎么决定的",
        "汇率是什么意思",
        "股价为什么会波动",
        "how is a stock price determined",
        "what is an exchange rate",
    ],
)
def test_conceptual_questions_on_live_topics_let_the_model_choose(query: str) -> None:
    # Live topic words alone must not force a search for a concept question.
    plan = build_tool_intent_plan(query)

    assert plan.preferred_first_tool is None


@pytest.mark.parametrize(
    "query",
    [
        "为什么最近油价上涨",
        "为什么这首歌最近很火",
        "汇率现在是多少",
        "explain today's stock market drop",
    ],
)
def test_conceptual_wording_with_freshness_cue_still_searches_first(query: str) -> None:
    assert build_tool_intent_plan(query).preferred_first_tool == "web_search"
