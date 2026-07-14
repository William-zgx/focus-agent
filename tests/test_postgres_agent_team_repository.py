from __future__ import annotations

import os
from typing import Any
from uuid import uuid4

import psycopg
import pytest

from focus_agent.core.agent_team import (
    AgentTeamArtifactKind,
    AgentTeamSession,
    AgentTeamSessionStatus,
    AgentTeamTask,
    AgentTeamTaskOutput,
    AgentTeamTaskRole,
    AgentTeamTaskStatus,
    EvidenceRecord,
    TaskCheckpoint,
    TaskRun,
    TaskRunEvent,
    ToolExecution,
)
from focus_agent.repositories.postgres_agent_team_repository import PostgresAgentTeamRepository


def _postgres_test_repository() -> tuple[PostgresAgentTeamRepository, str, str]:
    database_uri = os.environ.get("DATABASE_URI")
    if not database_uri:
        pytest.skip("DATABASE_URI is required for durable Postgres repository tests")
    schema_name = f"postgres_agent_team_records_{uuid4().hex}"
    separator = "&" if "?" in database_uri else "?"
    repository_uri = f"{database_uri}{separator}options=-csearch_path%3D{schema_name}"
    try:
        with psycopg.connect(database_uri, autocommit=True) as conn:
            conn.execute(f'CREATE SCHEMA "{schema_name}"')
    except psycopg.OperationalError as exc:
        pytest.skip(f"DATABASE_URI is not reachable for durable repository tests: {exc}")
    repository = PostgresAgentTeamRepository(repository_uri)
    repository.setup()
    return repository, database_uri, schema_name


def _durable_session_and_task() -> tuple[AgentTeamSession, AgentTeamTask]:
    session = AgentTeamSession(
        session_id="session-durable-records",
        root_thread_id="root-durable-records",
        user_id="user-durable-records",
        title="Durable execution records",
        goal="Persist all worktree execution records.",
        status=AgentTeamSessionStatus.PLANNING,
        created_at="2026-07-13T10:00:00+00:00",
        updated_at="2026-07-13T10:00:00+00:00",
    )
    task = AgentTeamTask(
        task_id="task-durable-records",
        session_id=session.session_id,
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal="Persist execution records.",
        status=AgentTeamTaskStatus.RUNNING,
        created_at="2026-07-13T10:00:01+00:00",
        updated_at="2026-07-13T10:00:01+00:00",
    )
    return session, task


def test_postgres_agent_team_repository_round_trips_models(monkeypatch):
    sessions: dict[str, dict[str, Any]] = {}
    tasks: dict[str, dict[str, Any]] = {}
    outputs: dict[str, dict[str, Any]] = {}
    executed: list[str] = []

    class FakeCursor:
        def __init__(self):
            self._fetchone: dict[str, Any] | None = None
            self._fetchall: list[dict[str, Any]] = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            normalized = " ".join(sql.split())
            executed.append(normalized)
            if normalized.startswith("SELECT version FROM focus_schema_migrations"):
                self._fetchone = None
                return
            if normalized.startswith("INSERT INTO focus_agent_team_sessions"):
                payload = params["data_json"].obj
                sessions[str(params["session_id"])] = {"data_json": payload}
                return
            if normalized.startswith(
                "SELECT data_json FROM focus_agent_team_sessions WHERE session_id"
            ):
                self._fetchone = sessions.get(str(params[0]))
                return
            if normalized.startswith(
                "SELECT data_json FROM focus_agent_team_sessions WHERE user_id"
            ):
                self._fetchall = [
                    value
                    for value in sessions.values()
                    if value["data_json"]["user_id"] == params[0]
                ]
                return
            if normalized.startswith("SELECT data_json FROM focus_agent_team_sessions"):
                self._fetchall = list(sessions.values())
                return
            if normalized.startswith("INSERT INTO focus_agent_team_tasks"):
                payload = params["data_json"].obj
                tasks[str(params["task_id"])] = {"data_json": payload}
                return
            if normalized.startswith("SELECT data_json FROM focus_agent_team_tasks WHERE task_id"):
                self._fetchone = tasks.get(str(params[0]))
                return
            if normalized.startswith(
                "SELECT data_json FROM focus_agent_team_tasks WHERE session_id"
            ):
                self._fetchall = [
                    value
                    for value in tasks.values()
                    if value["data_json"]["session_id"] == params[0]
                ]
                return
            if normalized.startswith("INSERT INTO focus_agent_team_outputs"):
                payload = params["data_json"].obj
                outputs[str(params["output_id"])] = {"data_json": payload}
                return
            if normalized.startswith(
                "SELECT data_json FROM focus_agent_team_outputs WHERE task_id"
            ):
                self._fetchall = [
                    value
                    for value in outputs.values()
                    if value["data_json"]["task_id"] == params[0]
                ]

        def executemany(self, sql, param_sets):
            for params in param_sets:
                self.execute(sql, params)

        def fetchone(self):
            return self._fetchone

        def fetchall(self):
            return self._fetchall

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(
        "focus_agent.repositories.postgres_agent_team_repository.psycopg.connect",
        lambda uri, **kwargs: FakeConnection(),
    )

    repo = PostgresAgentTeamRepository("postgresql://example")
    repo.setup()
    session = AgentTeamSession(
        session_id="session-1",
        root_thread_id="root-1",
        user_id="user-1",
        title="Agent Team",
        goal="Persist in Postgres",
        status=AgentTeamSessionStatus.PLANNING,
        created_at="2026-04-25T10:00:00+00:00",
        updated_at="2026-04-25T10:00:00+00:00",
    )
    task = AgentTeamTask(
        task_id="task-1",
        session_id="session-1",
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal="Implement repository",
        status=AgentTeamTaskStatus.RUNNING,
        agent_run_id="run-task-1",
        delegated_task_id="delegated-task-1",
        artifact_ids=["artifact-task-1"],
        execution_status="completed",
        changed_files=["src/focus_agent/repositories/postgres_agent_team_repository.py"],
        created_at="2026-04-25T10:01:00+00:00",
        updated_at="2026-04-25T10:01:00+00:00",
    )
    output = AgentTeamTaskOutput(
        output_id="output-1",
        task_id="task-1",
        kind=AgentTeamArtifactKind.TEST_REPORT,
        summary="Postgres round-trip works.",
        test_evidence=["pytest tests/test_postgres_agent_team_repository.py"],
        created_at="2026-04-25T10:02:00+00:00",
    )

    repo.create_session(session)
    repo.create_task(task)
    repo.add_task_output(output)
    repo.save_session(
        session.model_copy(
            update={
                "status": AgentTeamSessionStatus.AWAITING_REVIEW,
                "latest_merge_bundle": {
                    "session_id": "session-1",
                    "recommended_next_action": "split_followup",
                },
            }
        )
    )

    assert repo.get_session("session-1").status == AgentTeamSessionStatus.AWAITING_REVIEW
    assert repo.get_session("session-1").latest_merge_bundle == {
        "session_id": "session-1",
        "recommended_next_action": "split_followup",
    }
    assert [item.session_id for item in repo.list_sessions(user_id="user-1")] == ["session-1"]
    restored_task = repo.get_task("task-1")
    assert restored_task.changed_files == [
        "src/focus_agent/repositories/postgres_agent_team_repository.py"
    ]
    assert restored_task.agent_run_id == "run-task-1"
    assert restored_task.delegated_task_id == "delegated-task-1"
    assert restored_task.artifact_ids == ["artifact-task-1"]
    assert restored_task.execution_status == "completed"
    assert [item.task_id for item in repo.list_tasks(session_id="session-1")] == ["task-1"]
    assert repo.list_task_outputs(task_id="task-1")[0].test_evidence == [
        "pytest tests/test_postgres_agent_team_repository.py"
    ]
    assert any("CREATE TABLE IF NOT EXISTS focus_agent_team_sessions" in sql for sql in executed)


def test_postgres_execution_records_are_durable_and_enforce_run_ownership() -> None:
    repository, database_uri, schema_name = _postgres_test_repository()
    session, task = _durable_session_and_task()
    task_run = TaskRun(
        task_run_id="run-durable-records",
        task_id=task.task_id,
        session_id=session.session_id,
        status=AgentTeamTaskStatus.RUNNING,
        attempt=1,
        started_at="2026-07-13T10:01:00+00:00",
        metadata={"sandbox": "worktree"},
        created_at="2026-07-13T10:01:00+00:00",
        updated_at="2026-07-13T10:01:00+00:00",
    )
    checkpoints = [
        TaskCheckpoint(
            checkpoint_id="checkpoint-durable-1",
            task_run_id=task_run.task_run_id,
            task_id=task.task_id,
            session_id=session.session_id,
            sequence=1,
            checkpoint_type="tool_started",
            state={"round": 1},
            created_at="2026-07-13T10:01:01+00:00",
        ),
        TaskCheckpoint(
            checkpoint_id="checkpoint-durable-2",
            task_run_id=task_run.task_run_id,
            task_id=task.task_id,
            session_id=session.session_id,
            sequence=1,
            checkpoint_type="tool_finished",
            state={"round": 1, "passed": True},
            created_at="2026-07-13T10:01:02+00:00",
        ),
    ]
    tool_execution = ToolExecution(
        tool_execution_id="tool-durable-1",
        task_run_id=task_run.task_run_id,
        task_id=task.task_id,
        session_id=session.session_id,
        tool_name="pytest",
        status="completed",
        request={"command": "pytest -q"},
        response={"exit_code": 0},
        created_at="2026-07-13T10:01:03+00:00",
    )
    evidence = EvidenceRecord(
        evidence_id="evidence-durable-1",
        task_run_id=task_run.task_run_id,
        task_id=task.task_id,
        session_id=session.session_id,
        source_type="sandbox_command",
        summary="pytest passed.",
        metadata={"exit_code": 0},
        created_at="2026-07-13T10:01:04+00:00",
    )
    event = TaskRunEvent(
        event_id="event-durable-1",
        task_run_id=task_run.task_run_id,
        task_id=task.task_id,
        session_id=session.session_id,
        event_type="completed",
        status="completed",
        created_at="2026-07-13T10:01:05+00:00",
    )

    try:
        repository.create_session(session)
        repository.create_task(task)
        repository.create_task_run(task_run)
        for checkpoint in checkpoints:
            repository.append_task_checkpoint(checkpoint)
        repository.append_tool_execution(tool_execution)
        repository.append_evidence_record(evidence)
        repository.append_task_run_event(event)

        reloaded = PostgresAgentTeamRepository(repository.database_uri)
        assert reloaded.get_task_run(task_run.task_run_id) == task_run
        assert reloaded.list_task_runs(task_id=task.task_id) == [task_run]
        assert reloaded.list_task_checkpoints(task_run_id=task_run.task_run_id) == checkpoints
        assert reloaded.list_tool_executions(task_run_id=task_run.task_run_id) == [tool_execution]
        assert reloaded.list_evidence_records(task_run_id=task_run.task_run_id) == [evidence]
        assert reloaded.list_evidence_records(session_id=session.session_id) == [evidence]
        assert reloaded.list_task_run_events(task_run_id=task_run.task_run_id) == [event]

        with pytest.raises(ValueError, match="belongs to task"):
            reloaded.append_tool_execution(
                tool_execution.model_copy(update={"task_id": "other-task"})
            )

        with psycopg.connect(reloaded.database_uri) as conn:
            attempt = conn.execute(
                """
                SELECT attempt_id, task_id, session_id, metadata_json
                FROM focus_agent_team_task_attempts
                WHERE attempt_id = %s
                """,
                (task_run.task_run_id,),
            ).fetchone()
            checkpoint_rows = conn.execute(
                """
                SELECT attempt_id, checkpoint_sequence, metadata_json
                FROM focus_agent_team_checkpoints
                ORDER BY checkpoint_sequence
                """
            ).fetchall()
            evidence_row = conn.execute(
                """
                SELECT attempt_id, task_id, session_id, evidence_json
                FROM focus_agent_team_evidence
                WHERE evidence_id = %s
                """,
                (evidence.evidence_id,),
            ).fetchone()
            event_rows = conn.execute(
                """
                SELECT attempt_id, event_type, payload_json
                FROM focus_agent_team_events
                ORDER BY sequence
                """
            ).fetchall()

        assert attempt[:3] == (task_run.task_run_id, task.task_id, session.session_id)
        assert attempt[3]["_focus_agent_execution_record"]["task_run_id"] == task_run.task_run_id
        assert [(row[0], row[1]) for row in checkpoint_rows] == [
            (task_run.task_run_id, 0),
            (task_run.task_run_id, 1),
        ]
        assert all(
            row[2]["_focus_agent_execution_record"]["task_run_id"] == task_run.task_run_id
            for row in checkpoint_rows
        )
        assert evidence_row[:3] == (task_run.task_run_id, task.task_id, session.session_id)
        assert (
            evidence_row[3]["_focus_agent_execution_record"]["evidence_id"] == evidence.evidence_id
        )
        assert [row[0] for row in event_rows] == [task_run.task_run_id, task_run.task_run_id]
        assert {row[1] for row in event_rows} == {
            "_focus_agent_tool_execution",
            event.event_type,
        }
        assert all(
            row[2]["_focus_agent_execution_record"]["task_run_id"] == task_run.task_run_id
            for row in event_rows
        )
    finally:
        with psycopg.connect(database_uri, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')


def test_postgres_repository_overrides_v2_execution_memory_fallback() -> None:
    from focus_agent.repositories.agent_team_repository import AgentTeamRepository

    for method_name in (
        "create_task_run",
        "save_task_run",
        "get_task_run",
        "list_task_runs",
        "add_task_checkpoint",
        "list_task_checkpoints",
        "add_tool_execution",
        "list_tool_executions",
        "add_evidence_record",
        "list_evidence_records",
        "add_task_run_event",
        "list_task_run_events",
    ):
        assert getattr(PostgresAgentTeamRepository, method_name) is not getattr(
            AgentTeamRepository,
            method_name,
        )


def test_postgres_agent_team_repository_raises_key_error_for_missing_records(monkeypatch):
    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            self._fetchone = None

        def fetchone(self):
            return self._fetchone

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(
        "focus_agent.repositories.postgres_agent_team_repository.psycopg.connect",
        lambda uri, **kwargs: FakeConnection(),
    )

    repo = PostgresAgentTeamRepository("postgresql://example")

    try:
        repo.get_session("missing")
    except KeyError as exc:
        assert "Unknown agent team session: missing" in str(exc)
    else:
        raise AssertionError("expected missing session to raise KeyError")
