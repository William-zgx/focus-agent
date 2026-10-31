"""Precision/recall regressions for the lexical pre-turn branch intent detector."""

from __future__ import annotations

import pytest
from langchain.messages import AIMessage, HumanMessage

from focus_agent.branch_decision.scorers import score_branch_recommendation
from focus_agent.branch_decision.signals import collect_branch_recommendation_signals
from focus_agent.core.branching import BranchMeta

_HISTORY = {
    "messages": [
        HumanMessage(content="帮我把订单服务的重试逻辑改成指数退避"),
        AIMessage(content="好的，这里是修改方案……"),
    ]
}
_BRANCH_META = BranchMeta(
    branch_id="b1",
    root_thread_id="root",
    parent_thread_id="root",
    return_thread_id="root",
    branch_name="Temporal 调研",
    branch_depth=1,
)


def _recommend(message: str, *, on_branch: bool = False, values: dict | None = None):
    signals = collect_branch_recommendation_signals(
        message=message,
        values=values if values is not None else _HISTORY,
        branch_meta=_BRANCH_META if on_branch else None,
    )
    return score_branch_recommendation(signals=signals, min_confidence=0.72)


@pytest.mark.parametrize(
    "message",
    [
        "能不能深入解释一下这段代码为什么会死锁？",
        "展开说说第二点",
        "新建一个 config.yaml 文件",
        "新建一个 React 项目，用 Vite",
        "把这个函数 split 成两个",
        "帮我写一个 split 字符串的工具函数",
        "Please make the fork() call handle errors",
        "Let's parallelize the test runner",
        "Is there an alternative to using a mutex here?",
        "Can you explore the logs and tell me why it fails?",
        "这是一个新问题吗？还是之前那个 bug 复现了",
        "Create a new git branch for the login feature",
    ],
)
def test_ambiguous_keywords_do_not_recommend_a_branch(message: str) -> None:
    score = _recommend(message)

    assert score.action.value == "continue_current"


@pytest.mark.parametrize(
    "message",
    [
        "Don't fork, just answer: what's an alternative to Temporal?",
        "No branching please, explore the alternative here.",
        "不要开分支，直接在这里深入分析一下",
        "不用分支，展开说说第二点",
        "不用新建分支，直接在这里回答",
    ],
)
def test_negated_branch_requests_continue(message: str) -> None:
    score = _recommend(message)

    assert score.action.value == "continue_current"
    assert "route=continue_hint" in score.rationale


@pytest.mark.parametrize(
    ("message", "expected_action", "on_branch"),
    [
        ("帮我开一个分支研究一下用 Temporal 替代自研重试", "fork_child_branch", False),
        ("Please open a new branch for the Temporal migration study", "fork_child_branch", False),
        ("请开一个同级分支并行评估方案 B", "fork_sibling_branch", True),
    ],
)
def test_explicit_branch_commands_score_high(
    message: str, expected_action: str, on_branch: bool
) -> None:
    score = _recommend(message, on_branch=on_branch)

    assert score.action.value == expected_action
    assert score.score >= 0.95
    assert "route=explicit_branch" in score.rationale


@pytest.mark.parametrize(
    "message",
    [
        "单独深入研究一下 Kafka 的分区再平衡",
        "Let's explore the Kafka alternative separately",
        "换个方向并行探索东线备用方案",
    ],
)
def test_qualified_exploration_scores_below_explicit(message: str) -> None:
    score = _recommend(message)

    assert score.action.value == "fork_child_branch"
    assert 0.72 < score.score < 0.95
    assert "route=qualified_exploration" in score.rationale


def test_new_question_counts_as_topic_drift_only_at_start_or_before_colon() -> None:
    leading = _recommend("新问题：我们的前端打包为什么这么慢？")
    labelled = _recommend("我还有另一个问题：前端打包为什么这么慢？")
    inline = _recommend("这是一个新问题吗？还是之前那个 bug 复现了")

    assert leading.action.value == "fork_child_branch"
    assert "route=topic_drift" in leading.rationale
    assert labelled.action.value == "fork_child_branch"
    assert inline.action.value == "continue_current"


def test_scores_are_graded_by_signal_strength() -> None:
    explicit = _recommend("帮我开一个分支研究一下用 Temporal 替代自研重试")
    drift = _recommend("另一个问题：我们的前端打包为什么这么慢？")

    assert explicit.score > drift.score > 0.72


@pytest.mark.parametrize(
    ("message", "route"),
    [
        ("顺便问一下，Python 的 GIL 在 3.13 还存在吗？", "side_question"),
        ("By the way, what's the difference between Redis streams and Kafka?", "side_question"),
        ("btw is Kafka exactly-once by default?", "side_question"),
        ("对比一下方案A（重试队列）和方案B（死信队列）的优缺点", "comparison"),
        ("Compare approach A vs approach B for this migration", "comparison"),
        ("Postgres or MySQL, which one fits this workload?", "comparison"),
        ("先暂停一下，我遇到一个奇怪的 CI 报错要先排查：pip install 超时", "detour"),
        ("Hold on, I need to debug a flaky CI job first", "detour"),
    ],
)
def test_detours_produce_low_confidence_recommendation(message: str, route: str) -> None:
    score = _recommend(message)

    assert score.action.value == "fork_child_branch"
    assert f"route={route}" in score.rationale
    assert 0.72 < score.score < 0.86


def test_side_question_on_branch_targets_sibling() -> None:
    score = _recommend("顺便问一下，Cadence 的授权协议是什么？", on_branch=True)

    assert score.action.value == "fork_sibling_branch"


@pytest.mark.parametrize(
    "message",
    [
        "顺便把单测也补上",
        "btw, also rename the variable to retry_count.",
        "对比一下这两个函数的实现",
        "这个方案还是有问题，重试次数应该可配置？",
    ],
)
def test_detour_lookalikes_continue(message: str) -> None:
    assert _recommend(message).action.value == "continue_current"


def test_detours_require_history() -> None:
    score = _recommend("Could you compare option A and B?", values={"messages": []})

    assert score.action.value == "continue_current"


def test_detour_handoff_drops_side_question_prefix() -> None:
    from focus_agent.services.branches.actions import branch_handoff_message_from_text

    assert (
        branch_handoff_message_from_text("顺便问一下，Python 的 GIL 在 3.13 还存在吗？")
        == "Python 的 GIL 在 3.13 还存在吗？"
    )
