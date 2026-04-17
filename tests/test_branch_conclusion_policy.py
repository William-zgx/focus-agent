from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest
from langchain.messages import SystemMessage

from focus_agent.core.branching import (
    BranchRecord,
    BranchRole,
    BranchStatus,
    MergeDecision,
    MergeMode,
    MergeProposalOverrides,
    MergeProposal,
    MergeTarget,
)
from focus_agent.core.request_context import RequestContext
from focus_agent.core.types import FindingItem
from focus_agent.services.branches import BranchService
from focus_agent.config import Settings


class FakeRepo:
    def __init__(self, records: list[BranchRecord] | None = None):
        self.records = {record.branch_id: deepcopy(record) for record in records or []}
        self.by_child_thread = {record.child_thread_id: record.branch_id for record in records or []}
        self.thread_owners = {}
        for record in records or []:
            self.thread_owners[record.root_thread_id] = record.owner_user_id
            self.thread_owners[record.child_thread_id] = record.owner_user_id
            self.thread_owners.setdefault(record.parent_thread_id, record.owner_user_id)
        self.saved_proposals: list[tuple[str, MergeProposal]] = []
        self.saved_decisions: list[tuple[str, MergeDecision]] = []

    def assert_thread_owner(self, *, thread_id: str, owner_user_id: str) -> None:
        if self.thread_owners.get(thread_id) != owner_user_id:
            raise PermissionError(thread_id)

    def get_thread_owner(self, *, thread_id: str) -> str | None:
        return self.thread_owners.get(thread_id)

    def ensure_thread_owner(self, *, thread_id: str, root_thread_id: str, owner_user_id: str) -> None:
        del root_thread_id
        self.thread_owners[thread_id] = owner_user_id

    def create(self, record: BranchRecord) -> None:
        self.records[record.branch_id] = deepcopy(record)
        self.by_child_thread[record.child_thread_id] = record.branch_id
        self.thread_owners[record.child_thread_id] = record.owner_user_id

    def get_by_child_thread_id(self, child_thread_id: str) -> BranchRecord:
        return deepcopy(self.records[self.by_child_thread[child_thread_id]])

    def get(self, branch_id: str) -> BranchRecord:
        return deepcopy(self.records[branch_id])

    def save_merge_proposal(self, branch_id: str, proposal: MergeProposal) -> None:
        self.saved_proposals.append((branch_id, proposal))
        record = self.records[branch_id]
        self.records[branch_id] = record.model_copy(update={"merge_proposal": proposal.model_dump(mode="json")})

    def save_merge_decision(self, branch_id: str, decision: MergeDecision) -> None:
        self.saved_decisions.append((branch_id, decision))
        record = self.records[branch_id]
        self.records[branch_id] = record.model_copy(update={"merge_decision": decision.model_dump(mode="json")})

    def update_status(self, branch_id: str, status: BranchStatus) -> None:
        record = self.records[branch_id]
        self.records[branch_id] = record.model_copy(update={"branch_status": status})


class FakeGraph:
    def __init__(self, states: dict[str, dict]):
        self.states = {thread_id: deepcopy(values) for thread_id, values in states.items()}
        self.updates: list[tuple[str, dict, str]] = []

    def get_state(self, config):
        thread_id = config["configurable"]["thread_id"]
        return SimpleNamespace(values=deepcopy(self.states.get(thread_id, {})))

    def update_state(self, config, values, as_node):
        thread_id = config["configurable"]["thread_id"]
        state = self.states.setdefault(thread_id, {})
        for key, value in deepcopy(values).items():
            state[key] = value
        self.updates.append((thread_id, deepcopy(values), as_node))


class FakeMemoryWriter:
    def __init__(self):
        self.branch_writes: list[tuple[RequestContext, str, list[FindingItem]]] = []
        self.imported_conclusions: list[tuple[RequestContext, object]] = []
        self.promoted_findings: list[tuple[RequestContext, str, list[FindingItem]]] = []

    def write_branch_findings(self, *, context: RequestContext, branch_name: str, findings: list[FindingItem]) -> list[str]:
        self.branch_writes.append((context, branch_name, findings))
        return ["branch-memory-1"]

    def write_imported_conclusion(self, *, context: RequestContext, imported) -> str:
        self.imported_conclusions.append((context, imported))
        return "imported-1"

    def promote_branch_findings(self, *, context: RequestContext, branch_id: str, findings: list[FindingItem]) -> list[str]:
        self.promoted_findings.append((context, branch_id, findings))
        return ["promoted-1"]


def _make_record(
    *,
    branch_id: str = "branch-1",
    parent_thread_id: str = "root-1",
    child_thread_id: str = "child-1",
    return_thread_id: str | None = None,
    root_thread_id: str = "root-1",
) -> BranchRecord:
    return BranchRecord(
        branch_id=branch_id,
        root_thread_id=root_thread_id,
        parent_thread_id=parent_thread_id,
        child_thread_id=child_thread_id,
        return_thread_id=return_thread_id or parent_thread_id,
        owner_user_id="user-1",
        branch_name="Policy Branch",
        branch_role=BranchRole.DEEP_DIVE,
        branch_depth=1,
        branch_status=BranchStatus.ACTIVE,
    )


def test_fork_branch_populates_branch_meta_without_conclusion_policy():
    service = object.__new__(BranchService)
    service.repo = FakeRepo()
    service.graph = FakeGraph({"root-1": {}})
    service.thread_client = None
    service.proposal_model = None
    service.settings = SimpleNamespace(branch_max_depth=5)
    service.store = None
    service.memory_writer = None
    service.repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="user-1")

    record = service.fork_branch(parent_thread_id="root-1", user_id="user-1")

    child_state = service.graph.states[record.child_thread_id]
    assert "conclusion_policy" not in child_state["branch_meta"]


def test_branch_service_prefers_helper_model_for_internal_flows(monkeypatch):
    captured: dict[str, object] = {}

    def fake_create_chat_model(
        model_id: str,
        *,
        temperature: float,
        thinking_mode: str | None = None,
        settings=None,
    ):
        captured["model_id"] = model_id
        captured["temperature"] = temperature
        captured["thinking_mode"] = thinking_mode
        captured["settings"] = settings
        return object()

    monkeypatch.setattr("focus_agent.services.branches.create_chat_model", fake_create_chat_model)

    service = BranchService(
        settings=Settings(model="ollama:gemma4-hauhau:q8", helper_model="openai:deepseek-reasoner"),
        graph=object(),
        repo=FakeRepo(),
    )

    assert service.proposal_model is not None
    assert captured["model_id"] == "openai:deepseek-reasoner"
    assert captured["temperature"] == 0
    assert captured["thinking_mode"] is None
    assert captured["settings"] is not None


def test_branch_service_falls_back_to_main_model_when_helper_model_is_unset(monkeypatch):
    captured: dict[str, object] = {}

    def fake_create_chat_model(
        model_id: str,
        *,
        temperature: float,
        thinking_mode: str | None = None,
        settings=None,
    ):
        captured["model_id"] = model_id
        captured["temperature"] = temperature
        captured["thinking_mode"] = thinking_mode
        captured["settings"] = settings
        return object()

    monkeypatch.setattr("focus_agent.services.branches.create_chat_model", fake_create_chat_model)

    service = BranchService(
        settings=Settings(model="moonshot:kimi-k2.5", helper_model=None),
        graph=object(),
        repo=FakeRepo(),
    )

    assert service.proposal_model is not None
    assert captured["model_id"] == "moonshot:kimi-k2.5"
    assert captured["temperature"] == 0
    assert captured["thinking_mode"] is None
    assert captured["settings"] is not None


def test_fork_branch_registers_unseen_root_thread_before_first_branch():
    service = object.__new__(BranchService)
    service.repo = FakeRepo()
    service.graph = FakeGraph({"root-1": {}})
    service.thread_client = None
    service.proposal_model = None
    service.settings = SimpleNamespace(branch_max_depth=5)
    service.store = None
    service.memory_writer = None

    record = service.fork_branch(parent_thread_id="root-1", user_id="user-1")

    assert record.root_thread_id == "root-1"
    assert service.repo.thread_owners["root-1"] == "user-1"


def test_prepare_merge_proposal_persists_findings_and_proposal(monkeypatch):
    record = _make_record()
    service = object.__new__(BranchService)
    service.repo = FakeRepo([record])
    service.graph = FakeGraph({record.child_thread_id: {"branch_local_findings": [FindingItem(finding="Local finding")]}})
    service.store = object()
    service.memory_writer = FakeMemoryWriter()
    service.proposal_model = None

    monkeypatch.setattr(
        "focus_agent.services.branches.generate_merge_proposal",
        lambda *_args, **_kwargs: MergeProposal(summary="usable"),
    )

    proposal = service.prepare_merge_proposal(child_thread_id=record.child_thread_id, user_id="user-1")

    assert proposal.summary == "usable"
    assert service.memory_writer.branch_writes
    assert service.repo.saved_proposals
    child_updates = [update for update in service.graph.updates if update[0] == record.child_thread_id]
    assert child_updates[0][1]["branch_meta"]["branch_status"] == "preparing_merge_review"
    assert child_updates[-1][1]["branch_meta"]["branch_status"] == "awaiting_merge_review"


def test_prepare_merge_proposal_reverts_status_when_generation_fails(monkeypatch):
    record = _make_record()
    service = object.__new__(BranchService)
    service.repo = FakeRepo([record])
    service.graph = FakeGraph({record.child_thread_id: {}})
    service.store = None
    service.memory_writer = None
    service.proposal_model = None

    def _boom(*_args, **_kwargs):
        raise RuntimeError("proposal failed")

    monkeypatch.setattr("focus_agent.services.branches.generate_merge_proposal", _boom)

    with pytest.raises(RuntimeError, match="proposal failed"):
        service.prepare_merge_proposal(child_thread_id=record.child_thread_id, user_id="user-1")

    assert service.repo.get(record.branch_id).branch_status == BranchStatus.ACTIVE
    child_updates = [update for update in service.graph.updates if update[0] == record.child_thread_id]
    assert child_updates[0][1]["branch_meta"]["branch_status"] == "preparing_merge_review"
    assert child_updates[-1][1]["branch_meta"]["branch_status"] == "active"


def test_fork_branch_rejects_merged_parent_branch():
    parent_record = _make_record(
        branch_id="parent-branch",
        parent_thread_id="root-1",
        child_thread_id="child-merged",
    ).model_copy(update={"branch_status": BranchStatus.MERGED})
    service = object.__new__(BranchService)
    service.repo = FakeRepo([parent_record])
    service.graph = FakeGraph({"child-merged": {}})
    service.thread_client = None
    service.proposal_model = None
    service.settings = SimpleNamespace(branch_max_depth=5)
    service.store = None
    service.memory_writer = None

    with pytest.raises(ValueError, match="Merged branches cannot create new branches."):
        service.fork_branch(parent_thread_id="child-merged", user_id="user-1")


def test_apply_merge_decision_marks_branch_merged():
    record = _make_record()
    service = object.__new__(BranchService)
    service.repo = FakeRepo([record])
    service.graph = FakeGraph({record.child_thread_id: {"merge_proposal": {"summary": "unused"}}})
    service.store = None
    service.memory_writer = None

    imported = service.apply_merge_decision(
        child_thread_id=record.child_thread_id,
        decision=MergeDecision(approved=True, mode=MergeMode.SUMMARY_ONLY),
        context=RequestContext(user_id="user-1", root_thread_id=record.root_thread_id),
    )

    assert imported is not None
    assert service.repo.get(record.branch_id).branch_status == BranchStatus.MERGED
    child_updates = [update for update in service.graph.updates if update[0] == record.child_thread_id]
    assert child_updates[-1][1]["branch_meta"]["branch_status"] == "merged"


def test_apply_merge_decision_promotes_only_when_returning_to_root_main():
    record = _make_record(return_thread_id="root-1")
    proposal = MergeProposal(
        summary="Bring this back",
        key_findings=["Finding A"],
        evidence_refs=["doc-1"],
        recommended_import_mode=MergeMode.SUMMARY_PLUS_EVIDENCE,
    )
    service = object.__new__(BranchService)
    service.repo = FakeRepo([record])
    service.graph = FakeGraph(
        {
            record.child_thread_id: {
                "merge_proposal": proposal.model_dump(mode="json"),
                "branch_local_findings": [FindingItem(finding="Finding A", evidence_refs=["doc-1"])],
            },
            "root-1": {},
        }
    )
    service.store = object()
    service.memory_writer = FakeMemoryWriter()

    imported = service.apply_merge_decision(
        child_thread_id=record.child_thread_id,
        decision=MergeDecision(approved=True, mode=MergeMode.SUMMARY_PLUS_EVIDENCE),
        context=RequestContext(user_id="user-1", root_thread_id=record.root_thread_id),
    )

    assert imported is not None
    target_thread_id, update_values, update_node = next(
        update for update in service.graph.updates if update[0] == "root-1" and "merge_queue" in update[1]
    )
    assert target_thread_id == "root-1"
    assert update_node == "bootstrap_turn"
    assert isinstance(update_values["messages"][0], SystemMessage)
    assert "Imported conclusion from branch 'Policy Branch':" in update_values["messages"][0].content
    assert "Bring this back" in update_values["messages"][0].content
    assert update_values["rolling_summary"].endswith("Imported from Policy Branch: Bring this back")
    assert update_values["merge_queue"][0]["summary"] == "Bring this back"
    assert update_values["imported_findings"][0]["finding"] == "Finding A"
    assert update_values["imported_findings"][0]["evidence_refs"] == ["doc-1"]
    assert service.memory_writer.imported_conclusions
    assert service.memory_writer.promoted_findings


def test_apply_merge_decision_to_nested_parent_does_not_promote_root_memory():
    record = _make_record(
        parent_thread_id="parent-branch-thread",
        child_thread_id="child-nested",
        return_thread_id="parent-branch-thread",
    )
    proposal = MergeProposal(
        summary="Keep this with parent branch",
        key_findings=["Nested finding"],
        evidence_refs=["note-2"],
    )
    service = object.__new__(BranchService)
    service.repo = FakeRepo([record])
    service.graph = FakeGraph(
        {
            record.child_thread_id: {
                "merge_proposal": proposal.model_dump(mode="json"),
                "branch_local_findings": [FindingItem(finding="Nested finding", evidence_refs=["note-2"])],
            },
            "parent-branch-thread": {},
        }
    )
    service.store = object()
    service.memory_writer = FakeMemoryWriter()

    imported = service.apply_merge_decision(
        child_thread_id=record.child_thread_id,
        decision=MergeDecision(approved=True, mode=MergeMode.SUMMARY_ONLY),
        context=RequestContext(user_id="user-1", root_thread_id=record.root_thread_id),
    )

    assert imported is not None
    target_thread_id, update_values, _ = next(
        update for update in service.graph.updates if update[0] == "parent-branch-thread" and "merge_queue" in update[1]
    )
    assert target_thread_id == "parent-branch-thread"
    assert isinstance(update_values["messages"][0], SystemMessage)
    assert "Keep this with parent branch" in update_values["messages"][0].content
    assert update_values["merge_queue"][0]["summary"] == "Keep this with parent branch"
    assert update_values["imported_findings"][0]["finding"] == "Nested finding"
    assert update_values["imported_findings"][0]["evidence_refs"] == []
    assert service.memory_writer.imported_conclusions == []
    assert service.memory_writer.promoted_findings == []


def test_apply_merge_decision_uses_edited_merge_proposal():
    record = _make_record(return_thread_id="root-1")
    original = MergeProposal(
        summary="Original summary",
        key_findings=["Original finding"],
        evidence_refs=["doc-old"],
        artifacts=["artifact-old"],
    )
    service = object.__new__(BranchService)
    service.repo = FakeRepo([record])
    service.graph = FakeGraph(
        {
            record.child_thread_id: {
                "merge_proposal": original.model_dump(mode="json"),
            },
            "root-1": {},
        }
    )
    service.store = None
    service.memory_writer = None

    imported = service.apply_merge_decision(
        child_thread_id=record.child_thread_id,
        decision=MergeDecision(approved=True, mode=MergeMode.SUMMARY_PLUS_EVIDENCE),
        context=RequestContext(user_id="user-1", root_thread_id=record.root_thread_id),
        proposal_overrides=MergeProposalOverrides(
            summary="Edited summary",
            key_findings=["Edited finding"],
            evidence_refs=["doc-new"],
            artifacts=["artifact-new"],
        ),
    )

    assert imported is not None
    assert imported.summary == "Edited summary"
    assert imported.key_findings == ["Edited finding"]
    assert imported.evidence_refs == ["doc-new"]
    root_update = next(update for update in service.graph.updates if update[0] == "root-1" and "merge_queue" in update[1])
    assert root_update[1]["merge_queue"][0]["summary"] == "Edited summary"
    assert "Edited summary" in root_update[1]["messages"][0].content
    assert service.repo.saved_proposals[-1][1].summary == "Edited summary"


def test_apply_merge_decision_can_target_root_main_from_nested_branch():
    record = _make_record(
        parent_thread_id="parent-branch-thread",
        child_thread_id="child-nested",
        return_thread_id="parent-branch-thread",
    )
    proposal = MergeProposal(
        summary="Promote this straight to main",
        key_findings=["Root finding"],
        evidence_refs=["note-3"],
        recommended_import_mode=MergeMode.SUMMARY_PLUS_EVIDENCE,
    )
    service = object.__new__(BranchService)
    service.repo = FakeRepo([record])
    service.graph = FakeGraph(
        {
            record.child_thread_id: {
                "merge_proposal": proposal.model_dump(mode="json"),
                "branch_local_findings": [FindingItem(finding="Root finding", evidence_refs=["note-3"])],
            },
            "parent-branch-thread": {},
            "root-1": {},
        }
    )
    service.store = object()
    service.memory_writer = FakeMemoryWriter()

    imported = service.apply_merge_decision(
        child_thread_id=record.child_thread_id,
        decision=MergeDecision(
            approved=True,
            mode=MergeMode.SUMMARY_PLUS_EVIDENCE,
            target=MergeTarget.ROOT_THREAD,
        ),
        context=RequestContext(user_id="user-1", root_thread_id=record.root_thread_id),
    )

    assert imported is not None
    target_thread_id, update_values, _ = next(
        update for update in service.graph.updates if update[0] == "root-1" and "merge_queue" in update[1]
    )
    assert target_thread_id == "root-1"
    assert update_values["merge_queue"][0]["summary"] == "Promote this straight to main"
    assert update_values["imported_findings"][0]["finding"] == "Root finding"
    assert update_values["imported_findings"][0]["evidence_refs"] == ["note-3"]
    assert service.memory_writer.imported_conclusions
    assert service.memory_writer.promoted_findings
