from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from focus_agent.core.agent_team import (
    AgentTeamRecommendedAction,
    AgentTeamTaskRole,
)
from focus_agent.core.branching import BranchRole


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


_ROLE_TO_BRANCH_ROLE: dict[AgentTeamTaskRole, BranchRole] = {
    AgentTeamTaskRole.PLANNER: BranchRole.DEEP_DIVE,
    AgentTeamTaskRole.ARCHITECT: BranchRole.DEEP_DIVE,
    AgentTeamTaskRole.BACKEND_EXECUTOR: BranchRole.EXECUTE,
    AgentTeamTaskRole.FRONTEND_EXECUTOR: BranchRole.EXECUTE,
    AgentTeamTaskRole.TEST_ENGINEER: BranchRole.VERIFY,
    AgentTeamTaskRole.REVIEWER: BranchRole.VERIFY,
    AgentTeamTaskRole.VERIFIER: BranchRole.VERIFY,
    AgentTeamTaskRole.WRITER: BranchRole.WRITEUP,
}


class AgentTeamHelperMixin:
    @staticmethod
    def branch_role_for_task_role(role: AgentTeamTaskRole | str) -> BranchRole:
        return _ROLE_TO_BRANCH_ROLE[AgentTeamTaskRole(role)]

    @staticmethod
    def _default_branch_name(role: AgentTeamTaskRole) -> str:
        return role.value.replace("_", " ").title()

    @staticmethod
    def _merge_verification_summary(current: str | None, test_evidence: list[str]) -> str | None:
        evidence = _dedupe(test_evidence)
        if not evidence:
            return current
        if not current:
            return "\n".join(evidence)
        return "\n".join(_dedupe([current, *evidence]))

    @staticmethod
    def _compact_task_goal(goal: str, *, max_chars: int = 140) -> str:
        summary = goal.split("\n\nSession goal:", 1)[0].strip()
        summary = " ".join(summary.split())
        if len(summary) <= max_chars:
            return summary
        return f"{summary[: max_chars - 1].rstrip()}…"

    @staticmethod
    def _recommended_action(
        *,
        accepted_count: int,
        rejected_count: int,
        pending_count: int,
        blocked_count: int,
        risk_count: int,
    ) -> AgentTeamRecommendedAction:
        if accepted_count == 0 and rejected_count > 0 and pending_count == 0 and blocked_count == 0:
            return AgentTeamRecommendedAction.DISCARD
        if blocked_count or risk_count:
            return AgentTeamRecommendedAction.REQUEST_CHANGES
        if pending_count:
            return AgentTeamRecommendedAction.SPLIT_FOLLOWUP
        return AgentTeamRecommendedAction.MERGE


__all__ = ["AgentTeamHelperMixin", "_ROLE_TO_BRANCH_ROLE", "_dedupe", "_now"]
