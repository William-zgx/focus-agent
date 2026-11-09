from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from langchain.messages import AIMessage, HumanMessage, ToolMessage

from focus_agent.core.branching import MergeDecision, MergeMode, MergeProposal
from focus_agent.core.request_context import RequestContext
from focus_agent.core.types import PromptMode
from focus_agent.engine.local_persistence import PersistentInMemoryStore
from focus_agent.engine.loop.memory_nodes import branch_memory_tool_findings
from focus_agent.memory import MemoryRetriever, MemoryWriter
from focus_agent.memory.assembler import render_scoped_context_memories
from focus_agent.memory.models import (
    MemoryKind,
    MemoryScope,
    MemoryVisibility,
    MemoryWriteRequest,
)
from focus_agent.storage.namespaces import (
    conversation_main_namespace,
    root_thread_episodic_namespace,
)

from .test_branch_conclusion_policy import FakeMemoryWriter, _make_record
from .test_branch_merge_quality import _service

ROOT = "root-1"


def _turn_summary(text: str, *, branch_id: str | None) -> MemoryWriteRequest:
    return MemoryWriteRequest(
        kind=MemoryKind.TURN_SUMMARY,
        scope=MemoryScope.ROOT_THREAD,
        visibility=MemoryVisibility.PRIVATE,
        namespace=root_thread_episodic_namespace(ROOT),
        content=text,
        summary=text,
        source_branch_id=branch_id,
        root_thread_id=ROOT,
        user_id="user-1",
        importance=0.9,
    )


@pytest.fixture
def retriever(tmp_path):
    store = PersistentInMemoryStore(tmp_path / "store.pkl")
    writer = MemoryWriter(store=store)
    writer.write_records(
        [
            _turn_summary("yugabyte pricing secret from branch one", branch_id="b1"),
            _turn_summary("yugabyte pricing from main thread", branch_id=None),
            MemoryWriteRequest(
                kind=MemoryKind.IMPORTED_CONCLUSION,
                scope=MemoryScope.ROOT_THREAD,
                visibility=MemoryVisibility.SHARED,
                namespace=conversation_main_namespace(ROOT),
                content="yugabyte pricing approved conclusion",
                summary="yugabyte pricing approved conclusion",
                source_branch_id="b0",
                root_thread_id=ROOT,
                user_id="user-1",
                promoted_to_main=True,
            ),
        ]
    )
    return MemoryRetriever(store=store)


def _summaries(retriever, *, branch_id, state, mode=PromptMode.EXPLORE) -> set[str]:
    bundle = retriever.retrieve_for_turn(
        context=RequestContext(user_id="user-1", root_thread_id=ROOT, branch_id=branch_id),
        state=state,
        query="yugabyte pricing",
        prompt_mode=mode,
    )
    return {hit.record.summary for hit in bundle.hits}


@pytest.mark.parametrize("mode", [PromptMode.EXPLORE, PromptMode.EXECUTE])
def test_unmerged_branch_memory_is_hidden_from_main_and_siblings(retriever, mode):
    main = _summaries(retriever, branch_id=None, state={}, mode=mode)
    sibling = _summaries(
        retriever, branch_id="b2", state={"branch_meta": {"branch_id": "b2"}}, mode=mode
    )

    for visible in (main, sibling):
        assert "yugabyte pricing secret from branch one" not in visible
        assert "yugabyte pricing from main thread" in visible
        assert "yugabyte pricing approved conclusion" in visible


def test_branch_memory_stays_visible_in_its_branch_and_descendants(retriever):
    own = _summaries(retriever, branch_id="b1", state={"branch_meta": {"branch_id": "b1"}})
    grandchild = _summaries(
        retriever,
        branch_id="b1-child",
        state={"branch_meta": {"branch_id": "b1-child", "ancestor_branch_ids": ["b1"]}},
    )

    assert "yugabyte pricing secret from branch one" in own
    assert "yugabyte pricing secret from branch one" in grandchild


def test_scoped_render_drops_unmerged_branch_records_on_main():
    record = _turn_summary("branch-only claim", branch_id="b1").model_dump(mode="json")
    record["memory_id"] = "m-1"
    state = {"retrieved_memories": [record]}

    main_block = render_scoped_context_memories(
        state, prompt_mode=PromptMode.EXPLORE, represented_lines=[], fallback=""
    )
    branch_block = render_scoped_context_memories(
        {**state, "branch_meta": {"branch_id": "b1"}},
        prompt_mode=PromptMode.EXPLORE,
        represented_lines=[],
        fallback="",
    )

    assert "branch-only claim" not in main_block
    assert "branch-only claim" in branch_block


def test_hidden_branch_memories_do_not_take_main_thread_recall_slots(tmp_path):
    store = PersistentInMemoryStore(tmp_path / "store.pkl")
    writer = MemoryWriter(store=store)
    writer.write_records(
        [
            *[
                _turn_summary(f"yugabyte pricing branch detail {index}", branch_id="b1")
                for index in range(6)
            ],
            *[
                _turn_summary(f"yugabyte pricing main note {index}", branch_id=None)
                for index in range(4)
            ],
        ]
    )
    bundle = MemoryRetriever(store=store, default_limit=4).retrieve_for_turn(
        context=RequestContext(user_id="user-1", root_thread_id=ROOT),
        state={},
        query="yugabyte pricing",
        prompt_mode=PromptMode.EXPLORE,
    )

    summaries = {hit.record.summary for hit in bundle.hits}
    assert not any("branch detail" in summary for summary in summaries)
    assert len(summaries) == 4


def test_fork_records_ancestor_branch_ids():
    service = _service(
        {
            "parent-thread": {
                "messages": [HumanMessage(content="hi")],
                "branch_meta": {
                    "branch_id": "b1",
                    "root_thread_id": ROOT,
                    "branch_depth": 1,
                    "ancestor_branch_ids": ["b0"],
                },
            }
        }
    )

    record = service.fork_branch(parent_thread_id="parent-thread", user_id="user-1")

    meta = service.graph.states[record.child_thread_id]["branch_meta"]
    assert meta["ancestor_branch_ids"] == ["b0", "b1"]


def test_branch_memory_save_becomes_branch_local_finding():
    state = {
        "messages": [
            HumanMessage(content="remember this for the branch"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call-1",
                        "name": "memory_save",
                        "args": {"content": "Yugabyte needs 3 nodes", "scope": "branch"},
                    },
                    {
                        "id": "call-2",
                        "name": "memory_save",
                        "args": {"content": "User likes tea", "scope": "user"},
                    },
                ],
            ),
            ToolMessage(
                content=json.dumps({"saved": True, "scope": "branch"}), tool_call_id="call-1"
            ),
            ToolMessage(
                content=json.dumps({"saved": True, "scope": "user"}), tool_call_id="call-2"
            ),
            AIMessage(content="Saved."),
        ],
        "branch_local_findings": [],
    }

    findings = branch_memory_tool_findings(state, branch_id="b1")

    assert [item["finding"] for item in findings] == ["Yugabyte needs 3 nodes"]
    assert findings[0]["source_branch_id"] == "b1"
    assert branch_memory_tool_findings(state, branch_id=None) == []
    state["branch_local_findings"] = findings
    assert branch_memory_tool_findings(state, branch_id="b1") == []


def test_apply_writes_approved_findings_and_runs_promotion_with_curator():
    record = _make_record(return_thread_id=ROOT)
    proposal = MergeProposal(
        summary="Yugabyte fits",
        key_findings=["Yugabyte costs $1.5k/mo"],
        evidence_refs=["pricing"],
    )
    service = _service(
        {
            record.child_thread_id: {
                "merge_proposal": proposal.model_dump(mode="json"),
                "branch_local_findings": [],
            },
            ROOT: {},
        },
        records=[record],
    )
    service.store = SimpleNamespace(search=lambda *args, **kwargs: [])
    service.memory_writer = FakeMemoryWriter()
    service.settings = SimpleNamespace(
        branch_max_depth=5,
        agent_memory_curator_enabled=True,
        agent_memory_auto_promote_on_merge=True,
    )

    service.apply_merge_decision(
        child_thread_id=record.child_thread_id,
        decision=MergeDecision(approved=True, mode=MergeMode.SUMMARY_PLUS_EVIDENCE),
        context=RequestContext(user_id="user-1", root_thread_id=ROOT),
    )

    child_update = next(
        values
        for thread_id, values, _ in service.graph.updates
        if thread_id == record.child_thread_id and "branch_local_findings" in values
    )
    assert child_update["branch_local_findings"][0]["finding"] == "Yugabyte costs $1.5k/mo"
    assert [item.summary for item in service.memory_writer.promoted_findings] == [
        "Yugabyte costs $1.5k/mo"
    ]
    assert service.memory_writer.promoted_findings[0].evidence_refs == ["pricing"]
    decision = service.graph.states[ROOT]["memory_curator_decision"]
    assert decision["status"] == "ready"
