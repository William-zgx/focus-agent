"""Core domain models and prompt assembly utilities for Focus Agent."""

from .branching import (
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
from .context_policy import ContextSlice, assemble_context
from .merge_review import generate_merge_proposal
from .request_context import RequestContext
from .state import AgentState, initial_agent_state, normalize_agent_state, serialize_agent_state
from .types import (
    ArtifactRef,
    CitationRef,
    ConstraintItem,
    ContextBudget,
    FindingItem,
    PinnedFact,
    PromptMode,
    StateModel,
)

__all__ = [
    "AgentState",
    "ArtifactRef",
    "BranchMeta",
    "BranchRecord",
    "BranchRole",
    "BranchStatus",
    "BranchTreeNode",
    "CitationRef",
    "ConstraintItem",
    "ContextBudget",
    "ContextSlice",
    "FindingItem",
    "ImportedConclusion",
    "MergeDecision",
    "MergeMode",
    "MergeProposal",
    "PinnedFact",
    "PromptMode",
    "RequestContext",
    "StateModel",
    "assemble_context",
    "generate_merge_proposal",
    "initial_agent_state",
    "normalize_agent_state",
    "serialize_agent_state",
]
