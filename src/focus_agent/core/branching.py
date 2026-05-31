from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class BranchRole(StrEnum):
    MAIN = "main"
    EXPLORE_ALTERNATIVES = "explore_alternatives"
    DEEP_DIVE = "deep_dive"
    EXECUTE = "execute"
    VERIFY = "verify"
    WRITEUP = "writeup"


class BranchStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    PREPARING_MERGE_REVIEW = "preparing_merge_review"
    AWAITING_MERGE_REVIEW = "awaiting_merge_review"
    MERGED = "merged"
    DISCARDED = "discarded"
    CLOSED = "closed"


class BranchActionKind(StrEnum):
    FORK_SIBLING_BRANCH = "fork_sibling_branch"
    FORK_CHILD_BRANCH = "fork_child_branch"
    OPEN_EXISTING_BRANCH = "open_existing_branch"
    RETURN_PARENT_BRANCH = "return_parent_branch"


class BranchActionStatus(StrEnum):
    PENDING = "pending"
    EXECUTED = "executed"
    DISMISSED = "dismissed"
    FAILED = "failed"


class MergeMode(StrEnum):
    NONE = "none"
    SUMMARY_ONLY = "summary_only"
    SUMMARY_PLUS_EVIDENCE = "summary_plus_evidence"
    SELECTED_ARTIFACTS = "selected_artifacts"


class MergeTarget(StrEnum):
    RETURN_THREAD = "return_thread"
    ROOT_THREAD = "root_thread"


class BranchMeta(BaseModel):
    branch_id: str
    root_thread_id: str
    parent_thread_id: str
    return_thread_id: str
    branch_name: str
    branch_role: BranchRole = BranchRole.EXPLORE_ALTERNATIVES
    branch_depth: int = 1
    branch_status: BranchStatus = BranchStatus.ACTIVE
    is_archived: bool = False
    archived_at: str | None = None
    fork_checkpoint_id: str | None = None
    fork_strategy: str = "copy_thread"


class MergeProposal(BaseModel):
    summary: str = Field(description="Compact summary that can be imported to the parent thread.")
    key_findings: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    recommended_import_mode: MergeMode = MergeMode.SUMMARY_ONLY


class MergeProposalOverrides(BaseModel):
    summary: str | None = None
    key_findings: list[str] | None = None
    open_questions: list[str] | None = None
    evidence_refs: list[str] | None = None
    artifacts: list[str] | None = None
    recommended_import_mode: MergeMode | None = None


class MergeDecision(BaseModel):
    approved: bool = True
    mode: MergeMode = MergeMode.SUMMARY_ONLY
    target: MergeTarget = MergeTarget.RETURN_THREAD
    rationale: str | None = None
    selected_artifacts: list[str] = Field(default_factory=list)


class ImportedConclusion(BaseModel):
    branch_id: str
    branch_name: str
    mode: MergeMode
    summary: str
    key_findings: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    rationale: str | None = None


class BranchRecord(BaseModel):
    branch_id: str
    root_thread_id: str
    parent_thread_id: str
    child_thread_id: str
    return_thread_id: str
    owner_user_id: str = "unknown"
    branch_name: str
    branch_role: BranchRole
    branch_depth: int
    branch_status: BranchStatus
    is_archived: bool = False
    archived_at: str | None = None
    fork_checkpoint_id: str | None = None
    fork_strategy: str = "copy_thread"
    merge_proposal: dict[str, Any] | None = None
    merge_decision: dict[str, Any] | None = None


class ThreadResolution(BaseModel):
    input_thread_id: str
    root_thread_id: str
    source_thread_id: str
    branch_id: str | None = None
    is_root: bool = True
    branch_status: BranchStatus = BranchStatus.ACTIVE
    diagnostic: str = ""

    @classmethod
    def from_branch_record(
        cls, record: BranchRecord, *, input_thread_id: str | None = None
    ) -> ThreadResolution:
        return cls(
            input_thread_id=input_thread_id or record.child_thread_id,
            root_thread_id=record.root_thread_id,
            source_thread_id=record.child_thread_id,
            branch_id=record.branch_id,
            is_root=False,
            branch_status=record.branch_status,
            diagnostic="resolved_from_branch_child",
        )

    @classmethod
    def root(
        cls,
        thread_id: str,
        *,
        input_thread_id: str | None = None,
        root_thread_id: str | None = None,
        diagnostic: str = "",
    ) -> ThreadResolution:
        resolved_root = root_thread_id or thread_id
        return cls(
            input_thread_id=input_thread_id or thread_id,
            root_thread_id=resolved_root,
            source_thread_id=thread_id,
            branch_id=None,
            is_root=thread_id == resolved_root,
            branch_status=BranchStatus.ACTIVE,
            diagnostic=diagnostic,
        )


class BranchTreeNode(BaseModel):
    thread_id: str
    root_thread_id: str
    parent_thread_id: str | None = None
    branch_id: str | None = None
    branch_name: str = "main"
    branch_role: BranchRole = BranchRole.MAIN
    branch_status: BranchStatus = BranchStatus.ACTIVE
    is_archived: bool = False
    archived_at: str | None = None
    branch_depth: int = 0
    fork_strategy: str | None = None
    token_usage: dict[str, int] = Field(default_factory=dict)
    children: list[BranchTreeNode] = Field(default_factory=list)


class BranchActionNavigation(BaseModel):
    root_thread_id: str
    thread_id: str


class BranchActionProposal(BaseModel):
    action_id: str
    kind: BranchActionKind
    status: BranchActionStatus = BranchActionStatus.PENDING
    root_thread_id: str
    source_thread_id: str
    target_parent_thread_id: str
    suggested_branch_name: str | None = None
    branch_role: BranchRole = BranchRole.EXPLORE_ALTERNATIVES
    reason: str = ""
    created_at: str
    executed_at: str | None = None
    dismissed_at: str | None = None
    failed_at: str | None = None
    error: str | None = None
    navigation: BranchActionNavigation | None = None
    source: str | None = None
    source_decision_id: str | None = None
    suggested_branch_name_source: Literal["explicit", "inferred"] | None = None
    confidence: float | None = None
    rationale: str | None = None
    handoff_message: str | None = None


BranchTreeNode.model_rebuild()
