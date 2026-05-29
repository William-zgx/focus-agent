from __future__ import annotations

from typing import Any, Protocol

from ...core.branching import BranchActionKind, BranchActionNavigation


class BranchServiceProtocol(Protocol):
    def fork_branch(self, **kwargs: Any) -> Any: ...


def execute_branch_action_navigation(
    *,
    action: Any,
    user_id: str,
    branch_service: BranchServiceProtocol,
) -> tuple[Any | None, BranchActionNavigation]:
    branch_record = None
    if action.kind in {BranchActionKind.FORK_SIBLING_BRANCH, BranchActionKind.FORK_CHILD_BRANCH}:
        branch_record = branch_service.fork_branch(
            parent_thread_id=action.target_parent_thread_id,
            user_id=user_id,
            branch_name=None,
            name_source=action.suggested_branch_name,
            branch_role=action.branch_role,
        )
        return branch_record, BranchActionNavigation(
            root_thread_id=branch_record.root_thread_id,
            thread_id=branch_record.child_thread_id,
        )
    if action.kind in {
        BranchActionKind.RETURN_PARENT_BRANCH,
        BranchActionKind.OPEN_EXISTING_BRANCH,
    }:
        return None, BranchActionNavigation(
            root_thread_id=action.root_thread_id,
            thread_id=action.target_parent_thread_id,
        )
    raise ValueError(f"Unsupported branch action kind: {action.kind}")
