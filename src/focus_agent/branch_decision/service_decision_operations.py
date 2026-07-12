"""Decision event management operations for the branch decision service."""

from __future__ import annotations

from focus_agent.core.governance import (
    BranchDecisionAction,
    BranchDecisionEvent,
    BranchDecisionStatus,
    BranchDecisionSummary,
)
from focus_agent.core.repo_call import has_repo_method


class BranchDecisionServiceDecisionOperationsMixin:
    """Public decision-event query and lifecycle operations."""

    def list_decisions(
        self,
        *,
        thread_id: str,
        user_id: str,
        status: str | None = None,
        action: str | None = None,
        limit: int = 50,
    ) -> list[BranchDecisionEvent]:
        self._assert_thread_owner(thread_id=thread_id, user_id=user_id)
        return self.governance_repository.list_branch_decision_events(
            user_id=user_id,
            source_thread_id=thread_id,
            status=status,
            action=action,
            limit=limit,
        )

    def summary_for_thread(self, *, thread_id: str, user_id: str) -> BranchDecisionSummary:
        if not has_repo_method(self.governance_repository, "list_branch_decision_events"):
            return BranchDecisionSummary()
        events = self.governance_repository.list_branch_decision_events(
            user_id=user_id,
            source_thread_id=thread_id,
            limit=20,
        )
        latest = events[0] if events else None
        dismissed_count = sum(1 for item in events if item.status == BranchDecisionStatus.DISMISSED)
        pending_action_id = (
            latest.promoted_action_id
            if latest and latest.status == BranchDecisionStatus.PROMOTED
            else None
        )
        return BranchDecisionSummary(
            latest_decision=latest,
            actionable=bool(latest and latest.can_promote),
            pending_action_id=pending_action_id,
            dismissed_count=dismissed_count,
        )

    def promote_decision(
        self,
        *,
        thread_id: str,
        decision_id: str,
        user_id: str,
        request_id: str | None = None,
    ) -> BranchDecisionEvent:
        self._assert_thread_owner(thread_id=thread_id, user_id=user_id)
        event = self._require_event(decision_id)
        if event.source_thread_id != thread_id:
            raise PermissionError("Branch decision does not belong to this thread.")
        if event.user_id not in {None, user_id}:
            raise PermissionError("Branch decision is not owned by this user.")
        if event.status == BranchDecisionStatus.DISMISSED:
            raise ValueError("Dismissed branch decisions cannot be promoted.")
        if event.promoted_action_id:
            return event
        if event.action not in {
            BranchDecisionAction.SPLIT,
            BranchDecisionAction.FORK_CHILD_BRANCH,
            BranchDecisionAction.FORK_SIBLING_BRANCH,
        }:
            return self._update_event(
                event,
                status=BranchDecisionStatus.BLOCKED,
                error="Only branch fork decisions can be promoted to a branch action.",
                metadata={**event.metadata, "reason": "unsupported_promotion_action"},
            )
        return self._promote_branch_action_decision(
            event,
            user_id=user_id,
            request_id=request_id,
        )

    def dismiss_decision(
        self,
        *,
        thread_id: str,
        decision_id: str,
        user_id: str,
        reason: str | None = None,
    ) -> BranchDecisionEvent:
        self._assert_thread_owner(thread_id=thread_id, user_id=user_id)
        event = self._require_event(decision_id)
        if event.source_thread_id != thread_id:
            raise PermissionError("Branch decision does not belong to this thread.")
        if event.user_id not in {None, user_id}:
            raise PermissionError("Branch decision is not owned by this user.")
        return self._update_event(
            event,
            status=BranchDecisionStatus.DISMISSED,
            dismiss_reason=reason or "user_dismissed",
            executed_at=self._decision_event_timestamp(),
        )

    def _decision_event_timestamp(self) -> str:
        raise NotImplementedError


__all__ = ["BranchDecisionServiceDecisionOperationsMixin"]
