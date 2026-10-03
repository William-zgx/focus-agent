from types import SimpleNamespace

from langchain.messages import AIMessage, HumanMessage, ToolMessage

from focus_agent.core.context_compaction import (
    build_incremental_compaction_update,
    compaction_message_boundary,
    select_recent_messages,
)
from focus_agent.services.chat.context_compaction import ChatContextCompactionMixin


def _pair(index: int) -> list[object]:
    return [
        HumanMessage(content=f"human-{index}", id=f"human-{index}"),
        AIMessage(content=f"assistant-{index}", id=f"assistant-{index}"),
    ]


def test_incremental_cursor_shares_recent_window_and_keeps_recent_raw_out_of_summary():
    messages = [message for index in range(4) for message in _pair(index)]
    state = {
        "messages": messages,
        "context_budget": {
            "recent_message_limit": 2,
            "recent_message_token_limit": 100,
        },
    }

    first = build_incremental_compaction_update(state, now="2026-09-30T00:00:00+00:00")
    meta = first["context_compaction"]
    recent = select_recent_messages(state)

    assert [message.id for message in recent] == ["human-3", "assistant-3"]
    assert meta["source_message_cursor"] == 6
    assert meta["recent_message_ids"] == ["human-3", "assistant-3"]
    assert "human-3" not in first["rolling_summary"]
    assert "assistant-3" not in first["rolling_summary"]

    extended = {**state, "messages": [*messages, *_pair(4)]}
    second = build_incremental_compaction_update(extended, meta, now="2026-09-30T00:01:00+00:00")
    second_meta = second["context_compaction"]

    assert second_meta["source_message_cursor"] == 8
    assert second_meta["source_message_cursor_id"] == "assistant-3"
    assert [item["id"] for item in second_meta["history_excerpts"]].count("human-3") == 1
    assert second_meta["recent_message_ids"] == ["human-4", "assistant-4"]
    assert "human-3" in second["rolling_summary"]
    assert "human-4" not in second["rolling_summary"]


def test_selector_keeps_recent_messages_compatibility_and_default_token_window():
    state = {"recent_messages": _pair(0)}

    selected = select_recent_messages(state)
    update = build_incremental_compaction_update(state, now="2026-09-30T00:00:00+00:00")

    assert selected == state["recent_messages"]
    assert update["context_compaction"]["recent_token_limit"] == 16000


def test_structured_summary_uses_authoritative_fields_and_preserves_legacy_as_unverified():
    state = {
        "messages": [*_pair(0), HumanMessage(content="RECENT_RAW_UNSUMMARIZED", id="recent")],
        "rolling_summary": "Legacy summary that must not become an authoritative constraint.",
        "active_goal": "Choose a storage backend",
        "user_constraints": [{"constraint": "Must support offline recovery"}],
        "pinned_facts": [{"fact": "The deployment uses Postgres"}],
        "imported_findings": [
            {"finding": "Approved path is Postgres", "evidence_refs": ["merge-1"]}
        ],
        "branch_local_findings": [
            {"finding": "Local benchmark is incomplete", "evidence_refs": ["bench-1"]}
        ],
        "artifacts": [{"title": "Benchmark report", "uri": "artifact://bench"}],
        "citations": [{"label": "Decision record", "uri": "citation://decision"}],
        "context_budget": {"recent_message_limit": 1, "recent_message_token_limit": 100},
    }

    update = build_incremental_compaction_update(state, now="2026-09-30T00:00:00+00:00")
    summary = update["rolling_summary"]
    meta = update["context_compaction"]

    assert "Goal: Choose a storage backend" in summary
    assert "Constraints:" in summary
    assert "Approved findings:" in summary
    assert "Local findings pending review:" in summary
    assert "merge-1" in summary and "bench-1" in summary
    assert "artifact://bench" in summary and "citation://decision" in summary
    assert "RECENT_RAW_UNSUMMARIZED" not in summary
    assert "Legacy summary excerpts (unparsed; not authoritative):" in summary
    assert meta["legacy_summary_preserved"] is True
    assert meta["non_destructive"] is True
    assert "Goal: Choose a storage backend" not in meta["history_summary"]
    assert "Legacy summary excerpts (unparsed; not authoritative):" in meta["history_summary"]


def test_state_change_with_same_message_count_updates_summary_cursor_metadata():
    messages = [message for index in range(3) for message in _pair(index)]
    first_state = {
        "messages": messages,
        "imported_findings": [{"finding": "Approved baseline", "evidence_refs": ["e-0"]}],
        "context_budget": {"recent_message_limit": 2, "recent_message_token_limit": 100},
    }
    first = build_incremental_compaction_update(first_state, now="2026-09-30T00:00:00+00:00")

    second_state = {
        **first_state,
        "imported_findings": [
            *first_state["imported_findings"],
            {"finding": "Approved new evidence", "evidence_refs": ["e-1"]},
        ],
    }
    second = build_incremental_compaction_update(
        second_state, first["context_compaction"], now="2026-09-30T00:01:00+00:00"
    )
    meta = second["context_compaction"]

    assert meta["source_message_count"] == first["context_compaction"]["source_message_count"]
    assert meta["source_state_cursors"]["imported_findings"] == 2
    assert meta["status"] == "updated"
    assert meta["no_gain"] is False
    assert "Approved new evidence" in second["rolling_summary"]


def test_branch_change_resets_message_cursor_and_does_not_reuse_parent_history():
    messages = [
        HumanMessage(content="parent-only", id="parent-human"),
        AIMessage(content="parent-answer", id="parent-ai"),
        HumanMessage(content="local-question", id="local-human"),
        AIMessage(content="local-answer", id="local-ai"),
        HumanMessage(content="local-followup", id="local-followup-human"),
        AIMessage(content="local-followup-answer", id="local-followup-ai"),
    ]
    parent = {
        "messages": messages,
        "branch_meta": {"branch_id": "main"},
        "context_budget": {"recent_message_limit": 2, "recent_message_token_limit": 100},
    }
    parent_update = build_incremental_compaction_update(parent, now="2026-09-30T00:00:00+00:00")
    child = {
        **parent,
        "branch_meta": {
            "branch_id": "child",
            "branch_fork_message_count": 2,
        },
    }
    child_update = build_incremental_compaction_update(
        child, parent_update["context_compaction"], now="2026-09-30T00:01:00+00:00"
    )
    meta = child_update["context_compaction"]

    assert meta["source_branch_id"] == "child"
    assert meta["source_cursor_reset"] is True
    assert all(item["id"] not in {"parent-human", "parent-ai"} for item in meta["history_excerpts"])
    assert "parent-only" not in child_update["rolling_summary"]
    assert "local-question" in child_update["rolling_summary"]


def test_recent_boundary_keeps_a_complete_tool_round_when_count_or_token_cut_is_inside_it():
    messages = [
        HumanMessage(content="question", id="human"),
        AIMessage(
            content="",
            id="tool-call",
            tool_calls=[{"id": "call-1", "name": "lookup", "args": {}}],
        ),
        ToolMessage(content="tool result", id="tool-result", tool_call_id="call-1"),
        AIMessage(content="answer", id="answer"),
    ]

    boundary = compaction_message_boundary(
        messages,
        recent_limit=2,
        recent_token_limit=1,
    )

    assert boundary.prefix_end == 0
    assert [message.id for message in boundary.recent_messages] == [
        "human",
        "tool-call",
        "tool-result",
        "answer",
    ]


def test_auto_compaction_skips_unchanged_state_without_writing_again():
    class Graph:
        def __init__(self, values):
            self.values = values
            self.updates = []

        def get_state(self, _config):
            return SimpleNamespace(values=self.values)

        def update_state(self, _config, values, as_node=None):
            self.updates.append((values, as_node))
            self.values = {**self.values, **values}

    class Harness(ChatContextCompactionMixin):
        def __init__(self, values):
            self.runtime = SimpleNamespace(
                graph=Graph(values),
                settings=SimpleNamespace(
                    context_auto_compaction_post_turn_ratio=0.85,
                    context_auto_compaction_pre_send_ratio=0.92,
                ),
            )

        def _context_usage_payload(self, _values, *, draft_message=None):
            del draft_message
            return {
                "used_tokens": 90,
                "pretrim_tokens": 90,
                "posttrim_tokens": 90,
                "input_token_limit": 100,
                "prompt_chars": 90,
            }

    values = {
        "messages": _pair(0),
        "context_budget": {"recent_message_limit": 1, "recent_message_token_limit": 100},
    }
    harness = Harness(values)

    first = harness._compact_thread_context_locked(
        thread_id="thread-1",
        values=values,
        trigger="auto_post_turn",
        force=True,
    )
    second = harness._compact_thread_context_locked(
        thread_id="thread-1",
        values=values,
        trigger="auto_post_turn",
        force=False,
    )

    assert first is not None
    assert second is None
    assert len(harness.runtime.graph.updates) == 1


def test_required_overflow_with_zero_input_limit_is_treated_as_over_limit():
    assert (
        ChatContextCompactionMixin._pretrim_context_ratio(
            {"pretrim_tokens": 0, "input_token_limit": 0, "required_overflow": True}
        )
        == 1.0
    )
    assert (
        ChatContextCompactionMixin._pretrim_context_ratio(
            {"pretrim_tokens": 0, "input_token_limit": 0, "required_overflow": False}
        )
        == 0.0
    )
