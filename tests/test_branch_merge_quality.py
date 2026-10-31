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


def _apply(service, record, mode=MergeMode.SUMMARY_PLUS_EVIDENCE):
    return service.apply_merge_decision(
        child_thread_id=record.child_thread_id,
        decision=MergeDecision(approved=True, mode=mode),
        context=RequestContext(user_id="user-1", root_thread_id="root-1"),
    )


def _target_update(service, thread_id):
    return next(
        values
        for target, values, _ in service.graph.updates
        if target == thread_id and "merge_queue" in values
    )


def _proposal(**extra):
    payload = {
        "summary": "Yugabyte fits the budget",
        "key_findings": ["Yugabyte costs $1.5k/mo", "Yugabyte lacks feature X"],
        "open_questions": ["Is feature X required?"],
        "evidence_refs": ["pricing", "docs"],
        "artifacts": ["cost.csv"],
    }
    payload.update(extra)
    return MergeProposal.model_validate(payload)


def test_apply_gives_each_finding_its_own_evidence_and_rich_import_metadata():
    record = _make_record(return_thread_id="root-1")
    proposal = _proposal(
        finding_evidence_refs={
            "Yugabyte costs $1.5k/mo": ["pricing"],
            "Yugabyte lacks feature X": ["docs"],
        }
    )
    service = _service(
        {
            record.child_thread_id: {"merge_proposal": proposal.model_dump(mode="json")},
            "root-1": {},
        },
        records=[record],
    )

    _apply(service, record)

    update = _target_update(service, "root-1")
    assert [item["evidence_refs"] for item in update["imported_findings"]] == [
        ["pricing"],
        ["docs"],
    ]
    entry = update["merge_queue"][0]
    assert entry["open_questions"] == ["Is feature X required?"]
    assert entry["child_thread_id"] == record.child_thread_id
    assert entry["imported_at"]
    notice = update["messages"][0]
    branch_import = notice.response_metadata["focus_agent"]["metadata"]["branch_import"]
    assert set(branch_import) == {
        "branch_id",
        "branch_name",
        "child_thread_id",
        "summary",
        "key_findings",
        "open_questions",
        "evidence_refs",
        "artifacts",
        "imported_at",
    }
    assert branch_import["open_questions"] == ["Is feature X required?"]
    assert branch_import["artifacts"] == ["cost.csv"]
    assert branch_import["evidence_refs"] == ["pricing", "docs"]
    assert "Yugabyte fits the budget" in notice.content


def test_apply_keeps_flat_evidence_when_proposal_has_no_per_finding_refs():
    record = _make_record(return_thread_id="root-1")
    service = _service(
        {
            record.child_thread_id: {"merge_proposal": _proposal().model_dump(mode="json")},
            "root-1": {},
        },
        records=[record],
    )

    _apply(service, record)

    update = _target_update(service, "root-1")
    assert all(item["evidence_refs"] == ["pricing", "docs"] for item in update["imported_findings"])


def test_import_metadata_reaches_ui_through_serialize_message():
    from focus_agent.services.chat.serialization import serialize_message
    from focus_agent.services.chat.threads import ChatThreadAccessMixin

    record = _make_record(return_thread_id="root-1")
    service = _service(
        {
            record.child_thread_id: {"merge_proposal": _proposal().model_dump(mode="json")},
            "root-1": {},
        },
        records=[record],
    )
    _apply(service, record)
    update = _target_update(service, "root-1")

    payload = serialize_message(update["messages"][0])

    assert payload["metadata"]["branch_import"]["branch_name"] == "Policy Branch"
    assert payload["metadata"]["branch_import"]["key_findings"] == [
        "Yugabyte costs $1.5k/mo",
        "Yugabyte lacks feature X",
    ]
    # The chat-side backfill rebuilds the notice from merge_queue; identical text
    # means no duplicate import message is appended on thread reads.
    rebuilt = ChatThreadAccessMixin._imported_conclusion_message(update["merge_queue"][0])
    assert rebuilt == update["messages"][0].content


def test_nested_merge_records_import_in_receiving_branch_memory():
    parent = _make_record(
        branch_id="parent-branch",
        child_thread_id="parent-thread",
        parent_thread_id="root-1",
    )
    child = _make_record(
        branch_id="child-branch",
        child_thread_id="child-thread",
        parent_thread_id="parent-thread",
    )
    service = _service(
        {
            "child-thread": {"merge_proposal": _proposal().model_dump(mode="json")},
            "parent-thread": {},
            "root-1": {},
        },
        records=[parent, child],
    )
    service.store = object()
    service.memory_writer = FakeMemoryWriter()

    _apply(service, child)

    assert service.memory_writer.imported_conclusions == []
    assert service.memory_writer.promoted_findings == []
    context, _, findings = service.memory_writer.branch_writes[-1]
    assert context.branch_id == "parent-branch"
    assert [item.finding for item in findings] == [
        "Yugabyte fits the budget",
        "Yugabyte costs $1.5k/mo",
        "Yugabyte lacks feature X",
    ]
