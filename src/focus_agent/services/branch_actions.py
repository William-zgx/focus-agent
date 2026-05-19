"""Compatibility shim for ``focus_agent.services.branches.actions``."""

from focus_agent.services.branches.actions import (
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
from focus_agent.services.branches.actions import (
    _clean_name as _clean_name,
)
from focus_agent.services.branches.actions import (
    _compact as _compact,
)
from focus_agent.services.branches.actions import (
    _extract_branch_name as _extract_branch_name,
)
from focus_agent.services.branches.actions import (
    _extract_topic_name as _extract_topic_name,
)

__all__ = [
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
]
