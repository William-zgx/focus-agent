from __future__ import annotations

import pytest

from focus_agent.services.agent_team_approval_resume import (
    AgentTeamApprovalResumeService,
    AgentTeamApprovalStatus,
    InMemoryAgentTeamApprovalTaskState,
    PendingAgentTeamInvocation,
)


class MutableClock:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _invocation(
    *,
    approval_id: str = "approval-1",
    task_id: str = "task-1",
    expires_at: float = 200.0,
) -> PendingAgentTeamInvocation:
    return PendingAgentTeamInvocation(
        approval_id=approval_id,
        session_id="session-1",
        task_id=task_id,
        invocation_id="tool-call-1",
        tool_name="write_release_note",
        raw_args={
            "summary": "Publish safe release notes",
            "api_token": "secret-token",
            "nested": {"customer_secret": "nested-secret", "visible": "safe"},
        },
        checkpoint={"thread_id": "thread-1", "checkpoint_id": "checkpoint-7"},
        expires_at=expires_at,
        sensitive_arg_names=("summary",),
    )


def test_pending_invocation_separates_redacted_display_from_executor_resume_payload() -> None:
    service = AgentTeamApprovalResumeService(clock=MutableClock())

    pending = service.save_pending_invocation(_invocation())
    decision = service.approve("approval-1", decided_by="reviewer", reason="bounded change")
    job = service.get_resume_job_for_executor("approval-1")

    assert pending.status is AgentTeamApprovalStatus.PENDING
    assert pending.display_args == {
        "summary": "[REDACTED]",
        "api_token": "[REDACTED]",
        "nested": {"customer_secret": "[REDACTED]", "visible": "safe"},
    }
    assert not hasattr(pending, "raw_args")
    assert not hasattr(pending, "checkpoint")
    assert decision.approval.status is AgentTeamApprovalStatus.APPROVED
    assert decision.created_resume_job is True
    assert job is not None
    assert job.raw_args["api_token"] == "secret-token"
    assert job.checkpoint == {"thread_id": "thread-1", "checkpoint_id": "checkpoint-7"}


def test_repeated_approve_is_idempotent_and_creates_one_resume_job() -> None:
    service = AgentTeamApprovalResumeService(clock=MutableClock())
    service.save_pending_invocation(_invocation())

    first = service.approve("approval-1", decided_by="reviewer")
    second = service.approve("approval-1", decided_by="other-reviewer", reason="retry")

    assert first.created_resume_job is True
    assert second.created_resume_job is False
    assert second.approval.status is AgentTeamApprovalStatus.APPROVED
    assert second.approval.decided_by == "reviewer"
    assert len(service.list_resume_jobs_for_executor()) == 1
    assert service.list_resume_jobs_for_executor()[0].idempotency_key == (
        "agent-team-approval-resume:approval-1"
    )


def test_reject_is_idempotent_and_never_creates_resume_job() -> None:
    service = AgentTeamApprovalResumeService(clock=MutableClock())
    service.save_pending_invocation(_invocation())

    first = service.reject("approval-1", decided_by="reviewer", reason="unsafe")
    second = service.reject("approval-1", decided_by="other-reviewer")

    assert first.approval.status is AgentTeamApprovalStatus.REJECTED
    assert second.approval.status is AgentTeamApprovalStatus.REJECTED
    assert first.created_resume_job is False
    assert second.created_resume_job is False
    assert service.get_resume_job_for_executor("approval-1") is None


def test_expired_and_voided_approvals_cannot_transition_to_resume() -> None:
    clock = MutableClock()
    service = AgentTeamApprovalResumeService(clock=clock)
    service.save_pending_invocation(_invocation(expires_at=110.0))
    clock.now = 110.0

    expired = service.approve("approval-1", decided_by="reviewer")
    assert expired.approval.status is AgentTeamApprovalStatus.EXPIRED
    assert expired.created_resume_job is False
    assert service.get_resume_job_for_executor("approval-1") is None

    service.save_pending_invocation(_invocation(approval_id="approval-2"))
    voided = service.void_pending("approval-2", reason="session_closed")
    repeated = service.approve("approval-2", decided_by="reviewer")

    assert voided is not None
    assert voided.status is AgentTeamApprovalStatus.VOIDED
    assert repeated.approval.status is AgentTeamApprovalStatus.VOIDED
    assert repeated.created_resume_job is False


@pytest.mark.parametrize("lifecycle", ["cancel", "supersede"])
def test_cancelled_or_superseded_task_is_voided_without_resume(lifecycle: str) -> None:
    state = InMemoryAgentTeamApprovalTaskState()
    service = AgentTeamApprovalResumeService(task_state=state, clock=MutableClock())
    service.save_pending_invocation(_invocation())
    getattr(state, lifecycle)("task-1")

    decision = service.approve("approval-1", decided_by="reviewer")

    assert decision.approval.status is AgentTeamApprovalStatus.VOIDED
    assert decision.approval.reason == "task_cancelled_or_superseded"
    assert decision.created_resume_job is False
    assert service.get_resume_job_for_executor("approval-1") is None


def test_expire_pending_transitions_all_due_pending_records() -> None:
    clock = MutableClock()
    service = AgentTeamApprovalResumeService(clock=clock)
    service.save_pending_invocation(_invocation(approval_id="due", expires_at=100.0))
    service.save_pending_invocation(_invocation(approval_id="future", expires_at=101.0))

    assert service.expire_pending() == 1
    assert service.get_approval("due").status is AgentTeamApprovalStatus.EXPIRED
    assert service.get_approval("future").status is AgentTeamApprovalStatus.PENDING
