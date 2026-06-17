from __future__ import annotations

import json

from langchain.messages import AIMessage, ToolMessage

from focus_agent.engine.graph_evidence import normalize_evidence_bundle, normalize_evidence_ledger
from focus_agent.engine.graph_execution_contract import (
    build_execution_contract,
    evaluate_execution_contract,
    skill_execution_evidence_facts,
    tool_result_names,
    verify_answer_against_evidence,
)


def test_live_web_contract_requires_search_after_temporal_anchor_only():
    messages = [
        AIMessage(
            content="",
            tool_calls=[{"id": "time-1", "name": "current_utc_time", "args": {}}],
        ),
        ToolMessage(content="2026-05-14T00:00:00Z", tool_call_id="time-1"),
    ]
    contract = build_execution_contract(
        policy="live_web_research",
        temporal_anchor_required=True,
        available_tool_names=["current_utc_time", "web_search"],
    )

    evaluated = evaluate_execution_contract(
        contract,
        tool_results_seen=tool_result_names(messages),
        evidence_ledger=[],
        available_tool_names=["current_utc_time", "web_search"],
    )

    assert evaluated["status"] == "missing_required_tools"
    assert evaluated["missing"] == ["web_search"]


def test_skill_execution_contract_requires_primary_tool_result():
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "skill-1",
                    "name": "run_workspace_command",
                    "args": {"cwd": ".focus_agent/skills/stocks"},
                }
            ],
        ),
        ToolMessage(
            content='{"ok": true, "symbol": "601020.SS"}',
            tool_call_id="skill-1",
        ),
    ]
    contract = build_execution_contract(
        policy="execution",
        available_tool_names=["run_workspace_command", "web_search"],
        skill_execution_plan={
            "selected_skill_ids": ["stocks"],
            "primary_tools": ["run_workspace_command"],
            "supporting_tools": ["web_search"],
            "runtime_cwds": {"stocks": ".focus_agent/skills/stocks"},
            "policy_override": "execution",
        },
    )

    missing = evaluate_execution_contract(
        contract,
        tool_results_seen=[],
        evidence_ledger=[],
        available_tool_names=["run_workspace_command", "web_search"],
    )
    satisfied = evaluate_execution_contract(
        contract,
        tool_results_seen=tool_result_names(messages),
        evidence_ledger=[],
        available_tool_names=["run_workspace_command", "web_search"],
        skill_evidence_facts=skill_execution_evidence_facts(
            messages,
            required_tools=["run_workspace_command"],
        ),
    )

    assert contract["policy"] == "skill_execution"
    assert contract["required_tools"] == ["run_workspace_command"]
    assert missing["status"] == "missing_required_tools"
    assert satisfied["status"] == "satisfied"
    assert verify_answer_against_evidence(
        answer="华钰矿业行情来自 stocks Skill，代码 601020.SS。",
        contract=satisfied,
        evidence_ledger=[],
    )["status"] == "verified"


def test_skill_execution_contract_prefers_entrypoint_tool_when_declared():
    contract = build_execution_contract(
        policy="execution",
        available_tool_names=["run_workspace_command", "run_skill_entrypoint"],
        skill_execution_plan={
            "selected_skill_ids": ["china-stock-analysis"],
            "primary_tools": ["run_workspace_command", "run_skill_entrypoint"],
            "policy_override": "execution",
        },
    )

    assert contract["policy"] == "skill_execution"
    assert contract["required_tools"] == ["run_skill_entrypoint"]


def test_skill_execution_contract_ignores_error_tool_result():
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "skill-1",
                    "name": "run_workspace_command",
                    "args": {"cwd": ".focus_agent/skills/stocks"},
                }
            ],
        ),
        ToolMessage(
            content=json.dumps(
                {
                    "status": "error",
                    "tool": "run_workspace_command",
                    "error": "denied by approval response",
                }
            ),
            tool_call_id="skill-1",
            status="error",
        ),
    ]
    contract = build_execution_contract(
        policy="execution",
        available_tool_names=["run_workspace_command"],
        skill_execution_plan={
            "selected_skill_ids": ["stocks"],
            "primary_tools": ["run_workspace_command"],
            "policy_override": "execution",
        },
    )

    evaluated = evaluate_execution_contract(
        contract,
        tool_results_seen=tool_result_names(messages),
        evidence_ledger=[],
        available_tool_names=["run_workspace_command"],
    )

    assert tool_result_names(messages) == []
    assert evaluated["status"] == "missing_required_tools"


def test_skill_execution_contract_requires_evidence_facts_after_tool_success():
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "skill-1",
                    "name": "run_workspace_command",
                    "args": {"cwd": ".focus_agent/skills/stocks"},
                }
            ],
        ),
        ToolMessage(content="plain output without structured facts", tool_call_id="skill-1"),
    ]
    contract = build_execution_contract(
        policy="execution",
        available_tool_names=["run_workspace_command"],
        skill_execution_plan={
            "selected_skill_ids": ["stocks"],
            "primary_tools": ["run_workspace_command"],
            "policy_override": "execution",
        },
    )

    evaluated = evaluate_execution_contract(
        contract,
        tool_results_seen=tool_result_names(messages),
        evidence_ledger=[],
        available_tool_names=["run_workspace_command"],
        skill_evidence_facts=skill_execution_evidence_facts(
            messages,
            required_tools=["run_workspace_command"],
        ),
    )
    verification = verify_answer_against_evidence(
        answer="工具已经执行成功，可以回答。",
        contract=evaluated,
        evidence_ledger=[],
    )

    assert tool_result_names(messages) == ["run_workspace_command"]
    assert evaluated["status"] == "missing_required_tools"
    assert evaluated["missing"] == []
    assert evaluated["skill_evidence_facts"] == []
    assert verification["status"] == "unsupported"
    assert verification["repair_action"] == "fallback_to_tool_results"


def test_run_skill_entrypoint_success_requires_uncompacted_structured_payload():
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "skill-1",
                    "name": "run_skill_entrypoint",
                    "args": {
                        "skill_id": "china-stock-analysis",
                        "entrypoint": "analyze_a_stock",
                    },
                }
            ],
        ),
        ToolMessage(
            content=json.dumps(
                {
                    "tool": "run_skill_entrypoint",
                    "truncated_by_context_policy": True,
                }
            ),
            tool_call_id="skill-1",
        ),
    ]

    assert tool_result_names(messages) == []


def test_skill_execution_contract_ignores_failed_workspace_command_payload():
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "skill-1",
                    "name": "run_workspace_command",
                    "args": {"cwd": ".focus_agent/skills/stocks"},
                }
            ],
        ),
        ToolMessage(
            content=json.dumps(
                {
                    "command": ["python3", "scripts/stock_client.py", "quote"],
                    "cwd": ".focus_agent/skills/stocks",
                    "exit_code": 2,
                    "timed_out": False,
                    "stdout": "",
                    "stderr": "symbol not found",
                }
            ),
            tool_call_id="skill-1",
        ),
    ]
    contract = build_execution_contract(
        policy="execution",
        available_tool_names=["run_workspace_command"],
        skill_execution_plan={
            "selected_skill_ids": ["stocks"],
            "primary_tools": ["run_workspace_command"],
            "policy_override": "execution",
        },
    )

    evaluated = evaluate_execution_contract(
        contract,
        tool_results_seen=tool_result_names(messages),
        evidence_ledger=[],
        available_tool_names=["run_workspace_command"],
    )

    assert tool_result_names(messages) == []
    assert evaluated["status"] == "missing_required_tools"


def test_skill_execution_answer_must_reference_latest_skill_observation():
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "skill-1",
                    "name": "run_skill_entrypoint",
                    "args": {
                        "skill_id": "china-stock-analysis",
                        "entrypoint": "analyze_a_stock",
                    },
                }
            ],
        ),
        ToolMessage(
            content=json.dumps(
                {
                    "status": "completed",
                    "skill_id": "china-stock-analysis",
                    "entrypoint": "analyze_a_stock",
                    "run_id": "run-abc123",
                    "exit_code": 0,
                    "timed_out": False,
                    "stdout": json.dumps(
                        {
                            "status": "completed",
                            "code": "000063",
                            "generated_at": "2026-06-17T02:04:20",
                        }
                    ),
                }
            ),
            tool_call_id="skill-1",
        ),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "read-1",
                    "name": "read_file",
                    "args": {
                        "path": ".focus_agent/sandboxes/china-stock-analysis/runs/run-abc123/financial_analysis.json"
                    },
                }
            ],
        ),
        ToolMessage(
            content=json.dumps(
                {
                    "path": ".focus_agent/sandboxes/china-stock-analysis/runs/run-abc123/financial_analysis.json",
                    "content": "\n".join(
                        [
                            " 1 | {",
                            ' 2 |   "code": "000063",',
                            ' 3 |   "name": "中兴通讯",',
                            ' 4 |   "score": 50,',
                            ' 5 |   "profitability": {"assessment": "较弱 - ROE低于10%，盈利能力需要改善"}',
                            " 6 | }",
                        ]
                    ),
                }
            ),
            tool_call_id="read-1",
        ),
    ]
    contract = build_execution_contract(
        policy="execution",
        available_tool_names=["run_skill_entrypoint", "read_file"],
        skill_execution_plan={
            "selected_skill_ids": ["china-stock-analysis"],
            "primary_tools": ["run_skill_entrypoint"],
            "policy_override": "execution",
        },
    )
    evaluated = evaluate_execution_contract(
        contract,
        tool_results_seen=tool_result_names(messages),
        evidence_ledger=[],
        available_tool_names=["run_skill_entrypoint", "read_file"],
        skill_evidence_facts=skill_execution_evidence_facts(
            messages,
            required_tools=["run_skill_entrypoint"],
        ),
    )

    stale = verify_answer_against_evidence(
        answer="以下是基于 2019-2023 年数据的旧版报告，ROE 为 13.38%。",
        contract=evaluated,
        evidence_ledger=[],
    )
    grounded = verify_answer_against_evidence(
        answer="本次 run_id run-abc123 已完成，财务评分 50。",
        contract=evaluated,
        evidence_ledger=[],
    )

    assert evaluated["status"] == "satisfied"
    assert any(fact["key"] == "score" and fact["value"] == "50" for fact in evaluated["skill_evidence_facts"])
    assert stale["status"] == "unsupported"
    assert stale["repair_action"] == "fallback_to_tool_results"
    assert grounded["status"] == "verified"


def test_answer_verifier_flags_leader_visit_contradiction():
    messages = [
        AIMessage(content="", tool_calls=[{"id": "search-1", "name": "web_search", "args": {}}]),
        ToolMessage(
            content=json.dumps(
                {
                    "results": [
                        {
                            "title": "Xi welcomes Trump in Beijing",
                            "url": "https://www.reuters.com/world/example",
                            "content": "President Xi welcomed President Trump during a visit to China.",
                        }
                    ]
                }
            ),
            tool_call_id="search-1",
        ),
    ]
    ledger = normalize_evidence_ledger(messages, observed_at="2026-05-14T00:00:00Z")
    contract = evaluate_execution_contract(
        build_execution_contract(
            policy="live_web_research",
            available_tool_names=["web_search"],
        ),
        tool_results_seen=tool_result_names(messages),
        evidence_ledger=ledger,
        available_tool_names=["web_search"],
    )

    verification = verify_answer_against_evidence(
        answer="No leaders are visiting China.",
        contract=contract,
        evidence_ledger=ledger,
    )

    assert verification["status"] == "contradicted"
    assert verification["contradictions"]


def test_same_turn_unrelated_web_search_results_are_excluded_from_evidence():
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "weather-search",
                    "name": "web_search",
                    "args": {"query": "今天北京天气"},
                },
                {
                    "id": "sports-search",
                    "name": "web_search",
                    "args": {"query": "NBA finals schedule"},
                },
            ],
        ),
        ToolMessage(
            content=json.dumps(
                {
                    "query": "今天北京天气",
                    "results": [
                        {
                            "title": "Beijing weather",
                            "url": "https://weather.example/beijing",
                            "content": "Beijing is sunny today.",
                        }
                    ],
                }
            ),
            tool_call_id="weather-search",
        ),
        ToolMessage(
            content=json.dumps(
                {
                    "query": "NBA finals schedule",
                    "results": [
                        {
                            "title": "NBA finals",
                            "url": "https://sports.example/nba",
                            "content": "Basketball schedule.",
                        }
                    ],
                }
            ),
            tool_call_id="sports-search",
        ),
    ]

    bundle = normalize_evidence_bundle(
        messages,
        observed_at="2026-05-14T00:00:00Z",
        user_query="今天北京天气",
    )
    ledger = normalize_evidence_ledger(
        messages,
        observed_at="2026-05-14T00:00:00Z",
        user_query="今天北京天气",
    )

    assert [item["title"] for item in bundle] == ["Beijing weather"]
    assert [item["tool_call_id"] for item in ledger] == ["weather-search"]


def test_answer_verifier_flags_stale_temporal_evidence_for_refresh():
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "search-1",
                    "name": "web_search",
                    "args": {"query": "今天北京天气"},
                }
            ],
        ),
        ToolMessage(
            content=json.dumps(
                {
                    "query": "今天北京天气",
                    "results": [
                        {
                            "title": "Beijing weather forecast",
                            "url": "https://weather.example/beijing",
                            "content": "Beijing forecast from an old page.",
                            "published_at": "2026-05-01",
                        }
                    ],
                }
            ),
            tool_call_id="search-1",
        ),
    ]
    ledger = normalize_evidence_ledger(
        messages,
        observed_at="2026-05-14T00:00:00Z",
        user_query="今天北京天气",
    )
    contract = evaluate_execution_contract(
        build_execution_contract(
            policy="live_web_research",
            temporal_anchor_required=True,
            available_tool_names=["web_search"],
        ),
        tool_results_seen=tool_result_names(messages),
        evidence_ledger=ledger,
        available_tool_names=["web_search"],
        observed_at="2026-05-14T00:00:00Z",
        user_query="今天北京天气",
    )

    verification = verify_answer_against_evidence(
        answer="今天北京天气晴朗。",
        contract=contract,
        evidence_ledger=ledger,
    )

    assert verification["status"] == "unsupported"
    assert verification["repair_action"] == "refresh_stale_evidence"
    assert verification["stale_evidence"] is True
