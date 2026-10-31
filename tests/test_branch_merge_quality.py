from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain.messages import AIMessage, HumanMessage

from focus_agent.core.branching import MergeDecision, MergeMode, MergeProposal
from focus_agent.core.request_context import RequestContext
from focus_agent.services.branches import BranchService

from .test_branch_conclusion_policy import FakeGraph, FakeMemoryWriter, FakeRepo, _make_record


def _service(states: dict, records=()) -> BranchService:
    service = object.__new__(BranchService)
    service.repo = FakeRepo(list(records))
    service.graph = FakeGraph(states)
    service.thread_client = None
    service.proposal_model = None
    service.settings = SimpleNamespace(branch_max_depth=5)
    service.store = None
    service.memory_writer = None
    for thread_id in states:
        service.repo.ensure_thread_owner(
            thread_id=thread_id, root_thread_id="root-1", owner_user_id="user-1"
        )
    return service


def test_fork_records_inherited_counts_and_resets_evidence_ledger():
    service = _service(
        {
            "root-1": {
                "messages": [HumanMessage(content="hi"), AIMessage(content="hello")],
                "imported_findings": [{"finding": "a"}, {"finding": "b"}],
                "merge_queue": [{"branch_name": "x", "summary": "y"}],
                "citations": [{"label": "c"}],
                "evidence_ledger": [{"id": "ev-1"}],
            }
        }
    )

    record = service.fork_branch(parent_thread_id="root-1", user_id="user-1")

    child = service.graph.states[record.child_thread_id]
    assert child["branch_meta"]["fork_inherited_counts"] == {
        "imported_findings": 2,
        "merge_queue": 1,
        "branch_local_findings": 0,
        "citations": 1,
        "artifacts": 0,
    }
    assert child["evidence_ledger"] == []


def test_apply_refuses_empty_proposal_summary():
    record = _make_record(return_thread_id="root-1")
    service = _service(
        {
            record.child_thread_id: {
                "merge_proposal": MergeProposal(summary="").model_dump(mode="json")
            },
            "root-1": {},
        },
        records=[record],
    )
    service.store = object()
    service.memory_writer = FakeMemoryWriter()

    with pytest.raises(ValueError, match="no conclusion to import"):
        service.apply_merge_decision(
            child_thread_id=record.child_thread_id,
            decision=MergeDecision(approved=True, mode=MergeMode.SUMMARY_ONLY),
            context=RequestContext(user_id="user-1", root_thread_id="root-1"),
        )
    assert service.memory_writer.records == []
