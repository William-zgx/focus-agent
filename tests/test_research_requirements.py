from datetime import date

import pytest

from focus_agent.core.runtime_outcome import build_task_outcome
from focus_agent.engine.graph.policy import build_tool_intent_plan
from focus_agent.engine.graph_execution_contract import (
    build_execution_contract,
    evaluate_execution_contract,
    verify_answer_against_evidence,
)


@pytest.mark.parametrize(
    "query",
    [
        "最近两个月 AI Agent 在实际可用能力上有哪些进展？请给出发布日期、官方来源，区分已发布能力、预览和你的判断。",
        "最近机器人有哪些能力提升？请提供官方来源。",
        "What capabilities have browser agents gained recently? Cite official sources.",
        "读取 https://example.com/releases 并总结新增的可用能力。",
        "What skills have browser agents gained recently? Cite official sources.",
        "最近 AI agent skills 有哪些进展？请给出官方来源。",
        "Summarize AI agent capabilities. Cite the original sources.",
        "What capabilities? Include links to original announcements.",
        "请查一下 agent 能力的官方公告。",
    ],
)
def test_external_capability_questions_keep_web_tools(query):
    plan = build_tool_intent_plan(query)
    assert plan.policy == "live_web_research"
    assert "web" in plan.allowed_toolsets
    assert "web" not in plan.denied_toolsets


@pytest.mark.parametrize(
    "query",
    [
        "你现在有哪些可用能力？",
        "列出本地已安装的技能",
        "What capabilities are available to you now?",
        "查一下有没有 release readiness 相关能力",
        "请使用本周股票相关的 Skill 帮我分析走势",
    ],
)
def test_local_capability_requests_still_discover_skills(query):
    plan = build_tool_intent_plan(query)
    assert plan.policy == "workspace_lookup"
    assert plan.preferred_first_tool == "skills_search"
    assert plan.allowed_toolsets == ["skill"]


@pytest.mark.parametrize("policy", ["workspace_lookup", "direct_answer"])
def test_original_evidence_requirement_survives_wrong_route(policy):
    query = "最近两个月 AI Agent 有哪些进展？请给出发布日期、官方来源。"
    contract = build_execution_contract(
        policy=policy, user_query=query, available_tool_names=["skills_search"]
    )
    evaluated = evaluate_execution_contract(
        contract,
        tool_results_seen=["skills_search"],
        available_tool_names=["skills_search"],
        user_query=query,
    )
    verification = verify_answer_against_evidence(
        answer="我只能查询本地技能，请开启联网。", contract=evaluated
    )
    outcome = build_task_outcome(
        user_goal=query,
        execution_contract=evaluated,
        answer_verification=verification,
        final_answer="我只能查询本地技能，请开启联网。",
    )
    assert evaluated["required_evidence"] is True
    assert evaluated["status"] == "blocked"
    assert outcome["status"] == "blocked"


def test_explicit_no_web_request_does_not_require_web_evidence():
    contract = build_execution_contract(
        policy="direct_answer", user_query="不要联网，只解释如何判断官方来源的发布日期。"
    )
    assert contract["status"] == "not_required"


@pytest.mark.parametrize(
    "query",
    [
        "不要提供官方来源，只解释什么是发布日期",
        "please do not provide official sources, just explain",
    ],
)
def test_negated_source_requirements_do_not_force_research(query):
    from focus_agent.engine.graph.policy_intent_parsing import requires_external_evidence

    assert not requires_external_evidence(query)
    assert build_tool_intent_plan(query).policy == "direct_answer"


def test_external_sources_do_not_replace_explicit_skill_execution_contract():
    contract = build_execution_contract(
        policy="execution",
        user_query="使用新闻技能查询并提供官方来源。",
        available_tool_names=["run_skill_entrypoint"],
        skill_execution_plan={
            "selected_skill_ids": ["news"],
            "primary_tools": ["run_skill_entrypoint"],
        },
    )
    assert contract["policy"] == "skill_execution"
    assert contract["required_tools"] == ["run_skill_entrypoint"]


def test_page_read_requirement_survives_a_wrong_preferred_tool():
    contract = build_execution_contract(
        policy="workspace_lookup",
        preferred_first_tool="skills_search",
        user_query="读取 https://example.com/news 并引用正文。",
        available_tool_names=["skills_search", "web_search"],
    )
    assert contract["required_tools"] == ["web_fetch"]


def test_explicit_required_tool_does_not_disappear_when_unavailable():
    contract = build_execution_contract(
        policy="live_web_research",
        available_tool_names=["web_search"],
        required_web_tools=["web_search", "web_fetch"],
    )
    evaluated = evaluate_execution_contract(
        contract,
        tool_results_seen=["web_search"],
        available_tool_names=["web_search"],
        evidence_ledger=[{"url": "https://example.com"}],
    )
    assert evaluated["status"] == "blocked"
    assert evaluated["missing"] == ["web_fetch"]


@pytest.mark.parametrize(
    "query, start",
    [
        ("过去3周 Agent 的进展", "2026-09-18"),
        ("近两个月 Agent 的进展", "2026-08-10"),
        ("recent ten days of product news", "2026-09-29"),
        ("last 2 months of browser agent capabilities", "2026-08-10"),
    ],
)
def test_search_and_verification_share_explicit_window(query, start):
    from focus_agent.engine.graph.policy_temporal import _temporal_live_web_search_args
    from focus_agent.engine.graph_execution_contract import (
        _fresh_evidence_min_date,
        _query_needs_fresh_evidence,
    )

    assert _query_needs_fresh_evidence(query)
    assert _fresh_evidence_min_date(query, date(2026, 10, 8)).isoformat() == start
    args = _temporal_live_web_search_args(
        {"query": query},
        fallback_query=query,
        current_utc_time="2026-10-08T00:00:00Z",
    )
    assert start in args["query"]
    assert build_tool_intent_plan(query).temporal_anchor_required


def test_requested_publication_dates_cannot_use_fetch_time_instead():
    from focus_agent.engine.graph_execution_contract import _freshness_issue

    contract = {
        "policy": "live_web_research",
        "observed_at": "2026-10-08",
        "user_query": "最近两个月 Agent 有哪些进展？请给出发布日期。",
    }
    page = {
        "source_tool": "web_fetch",
        "evidence_layer": "body",
        "url": "https://example.com/news",
        "snippet": "New agent tools are available.",
    }
    reason, unknown = _freshness_issue(contract, [page])
    assert unknown
    assert "publication dates are unknown" in reason
