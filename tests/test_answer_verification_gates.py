from __future__ import annotations

from langchain.messages import AIMessage, HumanMessage

from focus_agent.engine.graph_memory_nodes import _should_extract_memories
from focus_agent.services.branch_merge import _merge_import_blocked_reason


def test_memory_extraction_skips_failed_answer_verification():
    state = {
        "messages": [HumanMessage(content="查一下新闻"), AIMessage(content="没有领导人访问。")],
        "answer_verification": {"status": "contradicted"},
    }

    assert _should_extract_memories(state) is False


def test_merge_import_gate_blocks_failed_answer_verification():
    assert (
        _merge_import_blocked_reason(
            {
                "plan_meta": {
                    "answer_verification": {
                        "status": "unsupported",
                    }
                }
            }
        )
        == "unsupported"
    )
