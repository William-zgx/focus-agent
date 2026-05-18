from __future__ import annotations

import json

from langchain.messages import AIMessage, ToolMessage

from focus_agent.engine.graph_evidence import normalize_evidence_ledger
from focus_agent.engine.graph_execution_contract import (
    build_execution_contract,
    evaluate_execution_contract,
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
