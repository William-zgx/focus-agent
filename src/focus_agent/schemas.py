"""Compatibility shim.

Canonical import:
    from focus_agent.core.branching import *
"""

from .core.branching import (
    BranchMeta,
    BranchRecord,
    BranchRole,
    BranchStatus,
    BranchTreeNode,
    ImportedConclusion,
    MergeDecision,
    MergeMode,
    MergeProposal,
)

__all__ = [
    "BranchMeta",
    "BranchRecord",
    "BranchRole",
    "BranchStatus",
    "BranchTreeNode",
    "ImportedConclusion",
    "MergeDecision",
    "MergeMode",
    "MergeProposal",
]
