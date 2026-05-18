from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from focus_agent.core.branching import (
    BranchActionNavigation,
    BranchActionProposal,
    BranchRecord,
    BranchRole,
    BranchTreeNode,
    ImportedConclusion,
    MergeMode,
    MergeProposalOverrides,
    MergeTarget,
)

from .chat import ThreadStateResponse


class BranchActionExecuteResponse(BaseModel):
    thread_state: ThreadStateResponse
    branch_action: BranchActionProposal
    branch_record: BranchRecord | None = None
    navigation: BranchActionNavigation | None = None


class ForkBranchRequest(BaseModel):
    parent_thread_id: str
    branch_name: str | None = None
    name_source: str | None = None
    branch_role: BranchRole = BranchRole.EXPLORE_ALTERNATIVES
    fork_checkpoint_id: str | None = None
    language: Literal["en", "zh"] | None = None
    user_id: str | None = None


class UpdateBranchNameRequest(BaseModel):
    branch_name: str


class PrepareMergeProposalRequest(BaseModel):
    user_id: str | None = None


class ApplyMergeDecisionRequest(BaseModel):
    approved: bool = True
    mode: MergeMode = MergeMode.SUMMARY_ONLY
    target: MergeTarget = MergeTarget.RETURN_THREAD
    rationale: str | None = None
    selected_artifacts: list[str] = Field(default_factory=list)
    proposal_overrides: MergeProposalOverrides | None = None
    user_id: str | None = None


class ApplyMergeDecisionResponse(BaseModel):
    imported: ImportedConclusion | None = None
    target_thread_id: str | None = None


class BranchTreeResponse(BaseModel):
    root: BranchTreeNode
    archived_branches: list[BranchTreeNode] = Field(default_factory=list)


__all__ = [
    "BranchActionExecuteResponse",
    "ForkBranchRequest",
    "UpdateBranchNameRequest",
    "PrepareMergeProposalRequest",
    "ApplyMergeDecisionRequest",
    "ApplyMergeDecisionResponse",
    "BranchTreeResponse",
]
