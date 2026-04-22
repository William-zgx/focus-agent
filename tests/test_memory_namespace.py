from focus_agent.services.branches import BranchService
from focus_agent.core.request_context import RequestContext
from focus_agent.storage.namespaces import (
    branch_namespace,
    branch_local_memory_namespace,
    branch_promoted_memory_namespace,
    conversation_main_namespace,
    conversation_namespace_for_context,
    is_user_profile_payload_allowed,
    project_memory_namespace,
    root_thread_episodic_namespace,
    root_thread_semantic_namespace,
    skill_memory_namespace,
    user_profile_namespace,
)
from focus_agent.core.types import FindingItem
from focus_agent.core.branching import BranchRecord, BranchRole, BranchStatus, ImportedConclusion, MergeMode


class FakeStore:
    def __init__(self):
        self.put_calls: list[tuple[tuple[str, ...], str, dict]] = []

    def put(self, namespace, key, value):
        self.put_calls.append((namespace, key, value))


def _make_branch_record() -> BranchRecord:
    return BranchRecord(
        branch_id="branch-1",
        root_thread_id="root-1",
        parent_thread_id="main-1",
        child_thread_id="child-1",
        return_thread_id="main-1",
        owner_user_id="user-1",
        branch_name="deep-dive",
        branch_role=BranchRole.DEEP_DIVE,
        branch_depth=1,
        branch_status=BranchStatus.ACTIVE,
    )


def test_memory_namespace_helpers():
    context = RequestContext(user_id="user-1", root_thread_id="root-1", branch_id="branch-1")

    assert user_profile_namespace("user-1") == ("user", "user-1", "profile")
    assert conversation_main_namespace("root-1") == ("conversation", "root-1", "main")
    assert root_thread_episodic_namespace("root-1") == ("conversation", "root-1", "episodic")
    assert root_thread_semantic_namespace("root-1") == ("conversation", "root-1", "semantic")
    assert branch_namespace("root-1", "branch-1") == ("conversation", "root-1", "branch", "branch-1")
    assert branch_local_memory_namespace("root-1", "branch-1") == (
        "conversation",
        "root-1",
        "branch",
        "branch-1",
        "local_memory",
    )
    assert branch_promoted_memory_namespace("root-1", "branch-1") == (
        "conversation",
        "root-1",
        "branch",
        "branch-1",
        "promoted_memory",
    )
    assert project_memory_namespace("project-1") == ("project", "project-1", "memory")
    assert skill_memory_namespace("research") == ("skill", "research", "memory")
    assert conversation_namespace_for_context(context) == ("conversation", "root-1", "branch", "branch-1")
    assert is_user_profile_payload_allowed({"type": "user_preference"}) is True
    assert is_user_profile_payload_allowed({"type": "promoted_branch_finding"}) is False


def test_branch_findings_are_written_to_branch_namespace_before_merge():
    service = object.__new__(BranchService)
    service.store = FakeStore()
    record = _make_branch_record()

    keys = service._persist_branch_findings_to_branch_memory(
        branch_record=record,
        findings=[FindingItem(finding="Branch-only result", evidence_refs=["doc-1"])],
    )

    assert len(keys) == 1
    namespace, _, payload = service.store.put_calls[0]
    assert namespace == ("conversation", "root-1", "branch", "branch-1")
    assert payload["type"] == "branch_finding"
    assert payload["summary"] == "Branch-only result"


def test_promote_branch_findings_to_main_memory_after_merge():
    service = object.__new__(BranchService)
    service.store = FakeStore()
    record = _make_branch_record()

    keys = service.promote_branch_findings_to_main_memory(
        branch_record=record,
        findings=[
            FindingItem(finding="Approved result", evidence_refs=["proof-1"], confidence=0.9),
            FindingItem(finding="Skip me", merge_importable=False),
        ],
    )

    assert len(keys) == 1
    namespace, _, payload = service.store.put_calls[0]
    assert namespace == ("conversation", "root-1", "main")
    assert payload["type"] == "promoted_branch_finding"
    assert payload["summary"] == "Approved result"
    assert payload["confidence"] == 0.9
    assert payload["merge_importable"] is True
    assert payload["promoted_to_main"] is True
    assert payload["source_branch_id"] == "branch-1"
    assert payload["source_thread_id"] == "main-1"
    assert {
        "audit:branch_merge_promotion",
        "target:conversation_main",
        "kind:branch_finding",
        "branch:branch-1",
        "role:deep_dive",
        "filter:merge_importable",
    }.issubset(set(payload["tags"]))


def test_promote_branch_findings_to_main_memory_skips_non_importable_findings():
    service = object.__new__(BranchService)
    service.store = FakeStore()
    record = _make_branch_record()

    keys = service.promote_branch_findings_to_main_memory(
        branch_record=record,
        findings=[FindingItem(finding="Stay local", merge_importable=False)],
    )

    assert keys == []
    assert service.store.put_calls == []


def test_imported_conclusion_main_memory_payload_has_audit_tags():
    service = object.__new__(BranchService)
    service.store = FakeStore()
    record = _make_branch_record()

    key = service._write_imported_conclusion_to_main_memory(
        branch_record=record,
        context=RequestContext(
            user_id="user-1",
            root_thread_id="root-1",
            parent_thread_id="root-1",
            branch_id="branch-1",
            branch_role="deep_dive",
        ),
        imported=ImportedConclusion(
            branch_id="branch-1",
            branch_name="deep-dive",
            mode=MergeMode.SUMMARY_PLUS_EVIDENCE,
            summary="Approved summary",
            key_findings=["Finding A"],
            evidence_refs=["proof-1"],
            artifacts=["artifact-1"],
        ),
    )

    assert key is not None
    namespace, _, payload = service.store.put_calls[0]
    assert namespace == ("conversation", "root-1", "main")
    assert payload["type"] == "imported_conclusion"
    assert payload["summary"] == "Approved summary"
    assert payload["promoted_to_main"] is True
    assert {
        "audit:branch_merge_promotion",
        "target:conversation_main",
        "kind:imported_conclusion",
        "branch:branch-1",
        "role:deep_dive",
        "mode:summary_plus_evidence",
    }.issubset(set(payload["tags"]))
