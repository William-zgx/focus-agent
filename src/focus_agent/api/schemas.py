"""Compatibility shim.

Canonical import:
    from focus_agent.api.contracts import *
"""

from .contracts import (
    ApplyMergeDecisionRequest,
    ApplyMergeDecisionResponse,
    BranchTreeResponse,
    ChatResumeRequest,
    ChatTurnRequest,
    ConversationListResponse,
    ConversationSummaryResponse,
    CreateConversationRequest,
    DemoTokenRequest,
    ForkBranchRequest,
    ModelCatalogResponse,
    ModelOptionResponse,
    PrepareMergeProposalRequest,
    PrincipalResponse,
    ThreadStateResponse,
    TokenResponse,
    UpdateBranchNameRequest,
    UpdateConversationRequest,
)

__all__ = [
    "ApplyMergeDecisionRequest",
    "ApplyMergeDecisionResponse",
    "BranchTreeResponse",
    "ChatResumeRequest",
    "ChatTurnRequest",
    "ConversationListResponse",
    "ConversationSummaryResponse",
    "CreateConversationRequest",
    "DemoTokenRequest",
    "ForkBranchRequest",
    "ModelCatalogResponse",
    "ModelOptionResponse",
    "PrepareMergeProposalRequest",
    "PrincipalResponse",
    "ThreadStateResponse",
    "TokenResponse",
    "UpdateBranchNameRequest",
    "UpdateConversationRequest",
]
