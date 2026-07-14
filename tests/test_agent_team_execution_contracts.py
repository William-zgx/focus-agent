from __future__ import annotations

import pytest
from pydantic import ValidationError

from focus_agent.core.agent_team import (
    AgentTeamEvidenceLevel,
    AgentTeamEvidenceVerdict,
    AgentTeamExecutionClass,
    AgentTeamSession,
    AgentTeamTask,
    AgentTeamTaskOutput,
    AgentTeamTaskRole,
    EvidenceRecord,
    TaskCheckpoint,
    TaskRun,
    TaskRunEvent,
    ToolExecution,
    is_execution_deliverable,
    is_verified_execution,
)
from focus_agent.repositories.agent_team_repository import InMemoryAgentTeamRepository
from focus_agent.repositories.sqlite_agent_team_repository import SQLiteAgentTeamRepository

_TIME = "2026-07-13T10:00:00+00:00"


def _task(*, task_id: str = "task-1") -> AgentTeamTask:
    return AgentTeamTask(
        task_id=task_id,
        session_id="session-1",
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal="Implement the execution contract.",
        created_at=_TIME,
        updated_at=_TIME,
    )


def test_execution_contract_fields_are_optional_and_default_to_safe_unset_provenance() -> None:
    session = AgentTeamSession(
        session_id="session-1",
        root_thread_id="thread-1",
        user_id="user-1",
        title="Execution contract",
        goal="Preserve legacy construction.",
        created_at=_TIME,
        updated_at=_TIME,
    )
    task = _task()
    output = AgentTeamTaskOutput(output_id="output-1", task_id=task.task_id, created_at=_TIME)

    for value in (session, task, output):
        assert value.task_run_id is None
        assert value.sandbox_id is None
        assert value.execution_profile is None
        assert value.execution_class is None
        assert value.evidence_level == AgentTeamEvidenceLevel.SYNTHETIC
        assert value.evidence_verdict == AgentTeamEvidenceVerdict.UNKNOWN
        assert value.evidence_summary is None
        assert value.revision_id is None
        assert value.row_version == 0
        assert value.cancel_epoch == 0
        assert value.deliverable is False


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        (
            {"evidence_level": AgentTeamEvidenceLevel.VERIFIED},
            "Fake execution cannot claim verified evidence",
        ),
        (
            {"evidence_verdict": AgentTeamEvidenceVerdict.VERIFIED},
            "Fake execution cannot claim a verified verdict",
        ),
        ({"deliverable": True}, "Fake execution cannot be marked deliverable"),
    ],
)
def test_fake_execution_cannot_claim_verified_or_deliverable_evidence(
    updates: dict[str, object],
    message: str,
) -> None:
    payload = _task().model_dump()
    payload["execution_class"] = AgentTeamExecutionClass.FAKE
    payload.update(updates)
    with pytest.raises(ValidationError, match=message):
        AgentTeamTask.model_validate(payload)


def test_sandbox_verified_execution_requires_verified_evidence_and_is_deliverable() -> None:
    output = AgentTeamTaskOutput(
        output_id="output-verified",
        task_id="task-1",
        task_run_id="run-1",
        sandbox_id="sandbox-1",
        execution_class=AgentTeamExecutionClass.SANDBOX_VERIFIED,
        evidence_level=AgentTeamEvidenceLevel.VERIFIED,
        evidence_verdict=AgentTeamEvidenceVerdict.VERIFIED,
        evidence_summary="pytest passed in the assigned sandbox.",
        revision_id="revision-1",
        row_version=2,
        cancel_epoch=1,
        deliverable=True,
        created_at=_TIME,
    )

    assert is_verified_execution(
        output.execution_class,
        output.evidence_level,
        output.evidence_verdict,
    )
    assert is_execution_deliverable(
        output.execution_class,
        output.evidence_level,
        output.evidence_verdict,
    )

    with pytest.raises(ValidationError, match="Sandbox-verified execution requires a sandbox_id"):
        AgentTeamTaskOutput(
            output_id="output-missing-sandbox",
            task_id="task-1",
            execution_class=AgentTeamExecutionClass.SANDBOX_VERIFIED,
            evidence_level=AgentTeamEvidenceLevel.VERIFIED,
            evidence_verdict=AgentTeamEvidenceVerdict.VERIFIED,
            created_at=_TIME,
        )


def test_in_memory_repository_appends_and_lists_v2_execution_records() -> None:
    repository = InMemoryAgentTeamRepository()
    task = _task()
    task_run = TaskRun(
        task_run_id="run-1",
        task_id=task.task_id,
        session_id=task.session_id,
        execution_class=AgentTeamExecutionClass.TOOL_AGENT,
        evidence_level=AgentTeamEvidenceLevel.WORKTREE,
        evidence_summary="Worktree was prepared.",
        created_at=_TIME,
    )
    checkpoint = TaskCheckpoint(
        checkpoint_id="checkpoint-1",
        task_run_id=task_run.task_run_id,
        task_id=task.task_id,
        sequence=1,
        summary="Files changed.",
        created_at="2026-07-13T10:01:00+00:00",
    )
    tool_execution = ToolExecution(
        tool_execution_id="tool-1",
        task_run_id=task_run.task_run_id,
        tool_name="pytest",
        status="completed",
        created_at="2026-07-13T10:02:00+00:00",
    )
    evidence = EvidenceRecord(
        evidence_id="evidence-1",
        task_run_id=task_run.task_run_id,
        task_id=task.task_id,
        session_id=task.session_id,
        source_type="test_report",
        summary="pytest passed.",
        evidence_level=AgentTeamEvidenceLevel.SANDBOX,
        created_at="2026-07-13T10:03:00+00:00",
    )
    event = TaskRunEvent(
        event_id="event-1",
        task_run_id=task_run.task_run_id,
        event_type="completed",
        status="completed",
        created_at="2026-07-13T10:04:00+00:00",
    )

    repository.create_task_run(task_run)
    repository.append_task_checkpoint(checkpoint)
    repository.append_tool_execution(tool_execution)
    repository.append_evidence_record(evidence)
    repository.append_task_run_event(event)

    assert repository.get_task_run(task_run.task_run_id) == task_run
    assert repository.list_task_runs(task_id=task.task_id) == [task_run]
    assert repository.list_task_checkpoints(task_run_id=task_run.task_run_id) == [checkpoint]
    assert repository.list_tool_executions(task_run_id=task_run.task_run_id) == [tool_execution]
    assert repository.list_evidence_records(task_run_id=task_run.task_run_id) == [evidence]
    assert repository.list_evidence_records(task_id=task.task_id) == [evidence]
    assert repository.list_task_run_events(task_run_id=task_run.task_run_id) == [event]


def test_legacy_sqlite_repository_inherits_v2_memory_fallback(tmp_path) -> None:
    repository = SQLiteAgentTeamRepository(str(tmp_path / "agent-team.sqlite3"))
    task_run = TaskRun(
        task_run_id="run-legacy-repository",
        task_id="task-1",
        session_id="session-1",
        created_at=_TIME,
    )

    repository.create_task_run(task_run)

    assert repository.get_task_run(task_run.task_run_id) == task_run
