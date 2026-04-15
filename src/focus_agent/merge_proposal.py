"""Compatibility shim.

Canonical import:
    from focus_agent.core.merge_review import fallback_merge_proposal, generate_merge_proposal
"""

from .core.merge_review import fallback_merge_proposal, generate_merge_proposal

__all__ = [
    "fallback_merge_proposal",
    "generate_merge_proposal",
]
