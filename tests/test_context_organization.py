from types import SimpleNamespace

from langchain.messages import AIMessage, HumanMessage, ToolMessage

from focus_agent.config import Settings
from focus_agent.core.branch_messages import branch_context_messages
from focus_agent.core.context_compaction import build_incremental_compaction_update
from focus_agent.core.context_policy import assemble_context
from focus_agent.core.request_context import RequestContext
from focus_agent.core.types import FindingItem, PromptMode
from focus_agent.engine.graph_memory_nodes import make_assemble_context_node
from focus_agent.engine.graph_tool_history_repair import _messages_for_model
from focus_agent.memory import MemoryKind, MemoryRecord, MemoryScope
from focus_agent.services.branches.lifecycle import _local_snapshot_seed_values
from focus_agent.skills import SkillRegistry


def test_branch_prompt_keeps_local_work_without_replaying_parent_exploration():
    messages = [
        HumanMessage(content="Compare every database"),
        AIMessage(content="Unreviewed parent hypothesis"),
        HumanMessage(content="Only investigate SQLite locking"),
        AIMessage(content="Local investigation"),
    ]
    state = {
        "messages": messages,
        "recent_messages": messages,
        "branch_meta": {"branch_id": "branch-a", "branch_fork_message_count": 2},
    }
    assert branch_context_messages(messages, values=state) == messages[2:]
    assert _messages_for_model(state) == messages[2:]
    assert assemble_context(state, PromptMode.EXPLORE).recent_messages == messages[2:]
    assert state["messages"] == messages


def test_branch_without_local_request_keeps_last_parent_exchange_as_seed():
    messages = [
        HumanMessage(content="Old unrelated request"),
        AIMessage(content="Old unrelated answer"),
        HumanMessage(content="Current research question"),
        AIMessage(content="Current handoff"),
    ]
    state = {"branch_meta": {"branch_id": "branch-a", "branch_fork_message_count": 4}}
    assert branch_context_messages(messages, values=state) == messages[2:]


def test_branch_recent_selection_preserves_local_messages_before_a_tool_exchange():
    local = [
        HumanMessage(content="Keep this local requirement", id="local-1"),
        AIMessage(content="Local answer", id="local-2"),
        HumanMessage(content="Investigate it", id="local-3"),
        AIMessage(content="", tool_calls=[{"id": "call-local", "name": "lookup", "args": {}}]),
        ToolMessage(content="Evidence", tool_call_id="call-local"),
    ]
    messages = [HumanMessage(content="Parent request"), AIMessage(content="Parent answer"), *local]
    result = _messages_for_model(
        {
            "messages": messages,
            "recent_messages": local[:3],
            "branch_meta": {"branch_id": "branch-a", "branch_fork_message_count": 2},
        }
    )
    assert [message.content for message in result[:3]] == [message.content for message in local[:3]]
    assert result[-1].tool_call_id == "call-local"


def test_graph_branch_assembly_does_not_filter_before_using_the_fork_cursor(tmp_path):
    state = {
        "messages": [
            HumanMessage(content="Parent investigation"),
            AIMessage(content="Unreviewed parent answer"),
            HumanMessage(content="新建子分支，详细的做一下去汉拿山的攻略。"),
            AIMessage(content="我已准备好分支切换确认项：创建子分支 一个新分支。请点击确认。"),
            HumanMessage(content="Only investigate the local question"),
        ],
        "branch_meta": {"branch_id": "branch-a", "branch_fork_message_count": 4},
    }
    node = make_assemble_context_node(settings=Settings(), skill_registry=SkillRegistry([tmp_path]))
    updates = node(
        state, SimpleNamespace(context=RequestContext(user_id="u", root_thread_id="root"))
    )
    assert [message.content for message in updates["recent_messages"]] == [
        "Only investigate the local question"
    ]


def test_local_branch_seed_does_not_inherit_unreviewed_parent_summary():
    parent = {
        "messages": [HumanMessage(content="Research")],
        "rolling_summary": "Parent-only unreviewed claims",
        "context_compaction": {"history": ["Parent-only unreviewed claims"]},
        "active_goal": "Design a storage system",
        "imported_findings": [{"finding": "Approved shared fact"}],
    }
    child = _local_snapshot_seed_values(parent)
    assert child["rolling_summary"] == ""
    assert child["context_compaction"] == {}
    assert child["active_goal"] == parent["active_goal"]
    assert child["imported_findings"] == parent["imported_findings"]
    assert parent["rolling_summary"] == "Parent-only unreviewed claims"


def _memory(**overrides):
    return MemoryRecord(
        **{
            "memory_id": "memory-a",
            "kind": MemoryKind.IMPORTED_CONCLUSION,
            "scope": MemoryScope.ROOT_THREAD,
            "content": "SQLite meets the local requirement",
            "source_branch_id": "branch-a",
            "evidence_refs": ["report:1"],
            "promoted_to_main": True,
            **overrides,
        }
    ).model_dump(mode="json")


def test_same_source_memory_and_imported_finding_are_rendered_once():
    text = "SQLite meets the local requirement"
    state = {
        "retrieved_memories": [_memory()],
        "memory_prompt_block": f"Stale duplicate: {text}",
        "imported_findings": [
            FindingItem(finding=text, source_branch_id="branch-a", evidence_refs=["report:1"])
        ],
    }
    prompt = assemble_context(state, PromptMode.SYNTHESIZE).render_prompt()
    assert prompt.count(text) == 1
    assert "report:1" in prompt


def test_distinct_evidence_is_not_silently_deduplicated():
    state = {
        "retrieved_memories": [_memory(evidence_refs=["report:2"])],
        "imported_findings": [
            FindingItem(
                finding="SQLite meets the local requirement",
                source_branch_id="branch-a",
                evidence_refs=["report:1"],
            )
        ],
    }
    prompt = assemble_context(state, PromptMode.SYNTHESIZE).render_prompt()
    assert "report:1" in prompt
    assert "report:2" in prompt


def test_retrieved_memory_deduplication_preserves_all_evidence_for_the_same_source():
    prompt = assemble_context(
        {
            "retrieved_memories": [
                _memory(),
                _memory(memory_id="memory-b", evidence_refs=["report:2"]),
            ]
        },
        PromptMode.SYNTHESIZE,
    ).render_prompt()
    assert "report:1" in prompt
    assert "report:2" in prompt


def test_retrieved_memory_claims_from_distinct_sources_remain_separate():
    prompt = assemble_context(
        {
            "retrieved_memories": [
                _memory(),
                _memory(memory_id="memory-b", source_branch_id="branch-b"),
            ]
        },
        PromptMode.SYNTHESIZE,
    ).render_prompt()
    assert prompt.count("SQLite meets the local requirement") == 2
    assert "source_branch=branch-a" in prompt
    assert "source_branch=branch-b" in prompt


def test_legacy_string_finding_does_not_crash_provenance_deduplication():
    prompt = assemble_context(
        {
            "imported_findings": ["Legacy finding without provenance"],
            "retrieved_memories": [_memory()],
        },
        PromptMode.SYNTHESIZE,
    ).render_prompt()
    assert "Legacy finding without provenance" in prompt
    assert "report:1" in prompt


def test_main_context_does_not_reintroduce_pending_branch_memory():
    state = {
        "retrieved_memories": [
            _memory(
                scope=MemoryScope.BRANCH,
                kind=MemoryKind.BRANCH_FINDING,
                content="Pending local hypothesis",
                promoted_to_main=False,
            )
        ],
        "memory_prompt_block": "Stale rendering: Pending local hypothesis",
    }
    assert (
        "Pending local hypothesis"
        not in assemble_context(state, PromptMode.SYNTHESIZE).render_prompt()
    )
    state["branch_meta"] = {"branch_id": "branch-a"}
    assert "Pending local hypothesis" in assemble_context(state, PromptMode.EXPLORE).render_prompt()


def test_compacted_snapshot_does_not_duplicate_or_revive_structured_constraints():
    state = {
        "messages": [HumanMessage(content="Choose a database")],
        "user_constraints": [{"constraint": "Use the current approved budget"}],
    }
    compacted = {**state, **build_incremental_compaction_update(state)}
    prompt = assemble_context(compacted, PromptMode.SYNTHESIZE).render_prompt()
    assert prompt.count("Use the current approved budget") == 1
    compacted["user_constraints"] = []
    prompt = assemble_context(compacted, PromptMode.SYNTHESIZE).render_prompt()
    assert "Use the current approved budget" not in prompt
