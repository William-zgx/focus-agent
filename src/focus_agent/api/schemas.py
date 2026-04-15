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
    DemoTokenRequest,
    ForkBranchRequest,
    ModelCatalogResponse,
    ModelOptionResponse,
    PrepareMergeProposalRequest,
    PrincipalResponse,
    ThreadStateResponse,
    TokenResponse,
)

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
