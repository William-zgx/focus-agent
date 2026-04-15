from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from focus_agent.core.branching import (
    BranchRole,
    MergeProposalOverrides,
    BranchTreeNode,
    ImportedConclusion,
    MergeMode,
    MergeTarget,
)


class ChatTurnRequest(BaseModel):
    thread_id: str
    message: str
    model: str | None = None
    thinking_mode: str | None = None
    skill_hints: list[str] = Field(default_factory=list)
    user_id: str | None = None


class ModelOptionResponse(BaseModel):
    id: str
    provider: str
    provider_label: str
    name: str
    label: str
    is_default: bool = False
    supports_thinking: bool = False
    default_thinking_enabled: bool = False


class ModelCatalogResponse(BaseModel):
    default_model: str
    models: list[ModelOptionResponse] = Field(default_factory=list)


class ChatResumeRequest(BaseModel):
    thread_id: str
    resume: Any
    user_id: str | None = None


class ThreadStateResponse(BaseModel):
    thread_id: str
    root_thread_id: str
    assistant_message: str | None = None
    rolling_summary: str = ''
    selected_model: str = ''
    selected_thinking_mode: str = ''
    branch_meta: dict[str, Any] | None = None
    merge_proposal: dict[str, Any] | None = None
    merge_decision: dict[str, Any] | None = None
    merge_queue: list[dict[str, Any]] = Field(default_factory=list)
    active_skill_ids: list[str] = Field(default_factory=list)
    messages: list[dict[str, Any]] = Field(default_factory=list)
    interrupts: list[Any] = Field(default_factory=list)
    trace: dict[str, Any] = Field(default_factory=dict)


class ForkBranchRequest(BaseModel):
    parent_thread_id: str
    branch_name: str | None = None
    name_source: str | None = None
    branch_role: BranchRole = BranchRole.EXPLORE_ALTERNATIVES
    fork_checkpoint_id: str | None = None
    user_id: str | None = None


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


class BranchTreeResponse(BaseModel):
    root: BranchTreeNode
    archived_branches: list[BranchTreeNode] = Field(default_factory=list)


class DemoTokenRequest(BaseModel):
    user_id: str = 'researcher-1'
    tenant_id: str | None = None
    scopes: list[str] = Field(default_factory=lambda: ['chat', 'branches'])


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = 'bearer'
    expires_in_seconds: int
    issuer: str


class PrincipalResponse(BaseModel):
    user_id: str
    tenant_id: str | None = None
    scopes: list[str] = Field(default_factory=list)
    auth_enabled: bool = True


__all__ = [
    "ApplyMergeDecisionRequest",
    "ApplyMergeDecisionResponse",
    "BranchTreeResponse",
    "ChatResumeRequest",
    "ChatTurnRequest",
    "DemoTokenRequest",
    "ForkBranchRequest",
    "ModelCatalogResponse",
    "ModelOptionResponse",
    "PrepareMergeProposalRequest",
    "PrincipalResponse",
    "ThreadStateResponse",
    "TokenResponse",
]
