from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

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


class BranchTreeNodeView(BranchTreeNode):
    """Branch tree node as served by the tree API, with activity metadata."""

    last_activity_at: str | None = Field(
        default=None,
        description=(
            "ISO timestamp of the thread's latest checkpoint (last turn or state "
            "update). Branch records carry no activity timestamp, so this is the "
            "best available signal; null when no checkpoint is readable."
        ),
    )
    children: list[BranchTreeNodeView] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _accept_core_node(cls, data: Any) -> Any:
        # Keep accepting plain core nodes so existing callers still validate.
        if isinstance(data, BranchTreeNode) and not isinstance(data, cls):
            return data.model_dump()
        return data

    @classmethod
    def from_node(
        cls, node: BranchTreeNode, *, activity_by_thread: dict[str, str]
    ) -> BranchTreeNodeView:
        payload = node.model_dump(exclude={"children"})
        payload["last_activity_at"] = activity_by_thread.get(node.thread_id)
        payload["children"] = [
            cls.from_node(child, activity_by_thread=activity_by_thread) for child in node.children
        ]
        return cls(**payload)


class BranchTreeResponse(BaseModel):
    root: BranchTreeNodeView
    archived_branches: list[BranchTreeNodeView] = Field(default_factory=list)


__all__ = [
    "BranchActionExecuteResponse",
    "ForkBranchRequest",
    "UpdateBranchNameRequest",
    "PrepareMergeProposalRequest",
    "ApplyMergeDecisionRequest",
    "ApplyMergeDecisionResponse",
    "BranchTreeNodeView",
    "BranchTreeResponse",
]
