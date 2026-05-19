"""Consolidated branches service modules.

Backward compatibility is preserved by legacy shims under focus_agent.services.branch_*.py.
"""

from focus_agent.core.merge_review import generate_merge_proposal

from .actions import (
    BranchNamingPolicyMixin,
    branch_action_audit_event,
    branch_handoff_message_from_text,
    build_branch_action_proposal,
    dismissal_message,
    execution_message,
    infer_suggested_branch_name,
    is_branch_action_confirmation,
    is_branch_action_dismissal,
    is_branch_action_request,
    latest_pending_branch_action,
    mark_branch_action_dismissed,
    mark_branch_action_executed,
    mark_branch_action_failed,
    normalize_branch_actions,
    proposal_message,
    replace_branch_action,
    requested_branch_action_kind,
    serialize_branch_actions,
    target_parent_thread_id,
    utc_iso,
)
from .merge import BranchMemoryPromotionMixin, BranchMergeCoordinator
from .service import BranchService, create_chat_model

__all__ = [
    "BranchService",
    "create_chat_model",
    "utc_iso",
    "normalize_branch_actions",
    "serialize_branch_actions",
    "latest_pending_branch_action",
    "is_branch_action_confirmation",
    "is_branch_action_dismissal",
    "is_branch_action_request",
    "requested_branch_action_kind",
    "target_parent_thread_id",
    "branch_handoff_message_from_text",
    "infer_suggested_branch_name",
    "build_branch_action_proposal",
    "replace_branch_action",
    "mark_branch_action_executed",
    "mark_branch_action_dismissed",
    "mark_branch_action_failed",
    "branch_action_audit_event",
    "proposal_message",
    "execution_message",
    "dismissal_message",
    "BranchNamingPolicyMixin",
    "BranchMergeCoordinator",
    "BranchMemoryPromotionMixin",
    "generate_merge_proposal",
]
