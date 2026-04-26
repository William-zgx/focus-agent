from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class BranchRole(str, Enum):
    MAIN = "main"
    EXPLORE_ALTERNATIVES = "explore_alternatives"
    DEEP_DIVE = "deep_dive"
    EXECUTE = "execute"
    VERIFY = "verify"
    WRITEUP = "writeup"


class BranchStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    PREPARING_MERGE_REVIEW = "preparing_merge_review"
    AWAITING_MERGE_REVIEW = "awaiting_merge_review"
    MERGED = "merged"
    DISCARDED = "discarded"
    CLOSED = "closed"


class BranchActionKind(str, Enum):
    FORK_SIBLING_BRANCH = "fork_sibling_branch"
    FORK_CHILD_BRANCH = "fork_child_branch"
    OPEN_EXISTING_BRANCH = "open_existing_branch"
    RETURN_PARENT_BRANCH = "return_parent_branch"


class BranchActionStatus(str, Enum):
    PENDING = "pending"
    EXECUTED = "executed"
    DISMISSED = "dismissed"
    FAILED = "failed"


class MergeMode(str, Enum):
    NONE = "none"
    SUMMARY_ONLY = "summary_only"
    SUMMARY_PLUS_EVIDENCE = "summary_plus_evidence"
    SELECTED_ARTIFACTS = "selected_artifacts"


class MergeTarget(str, Enum):
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
    owner_user_id: str = 'unknown'
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
    children: list["BranchTreeNode"] = Field(default_factory=list)


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


BranchTreeNode.model_rebuild()
