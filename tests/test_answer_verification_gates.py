from __future__ import annotations

import pytest
from langchain.messages import AIMessage, HumanMessage

from focus_agent.engine.graph_memory_nodes import _should_extract_memories
from focus_agent.services.branches.merge import _merge_import_blocked_reason


def test_memory_extraction_skips_failed_answer_verification():
    state = {
        "messages": [HumanMessage(content="查一下新闻"), AIMessage(content="没有领导人访问。")],
        "answer_verification": {"status": "contradicted"},
    }

    assert _should_extract_memories(state) is False


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        # Evidence contradicts the conclusion: the only status that still blocks.
        ("contradicted", "contradicted"),
        # Unverified: nothing was proven either way, so a user-approved import stands.
        ("unsupported", ""),
        ("blocked", ""),
    ],
)
def test_merge_import_gate_only_blocks_contradicted_answers(status: str, expected: str):
    assert (
        _merge_import_blocked_reason({"plan_meta": {"answer_verification": {"status": status}}})
        == expected
    )


def test_merge_import_gate_blocks_contradicted_at_top_level():
    assert (
        _merge_import_blocked_reason({"answer_verification": {"status": "contradicted"}})
        == "contradicted"
    )


def test_merge_import_gate_allows_verified_and_missing_verification():
    assert _merge_import_blocked_reason({"answer_verification": {"status": "verified"}}) == ""
    assert _merge_import_blocked_reason({"answer_verification": {"status": "not_required"}}) == ""
    assert _merge_import_blocked_reason({}) == ""
