from __future__ import annotations

from typing import Any

from focus_agent.core.agent_team import (
    AgentTeamArtifactKind,
    AgentTeamSession,
    AgentTeamSessionStatus,
    AgentTeamTask,
    AgentTeamTaskOutput,
    AgentTeamTaskRole,
    AgentTeamTaskStatus,
)
from focus_agent.repositories.postgres_agent_team_repository import PostgresAgentTeamRepository


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
            if normalized.startswith("SELECT data_json FROM focus_agent_team_sessions WHERE session_id"):
                self._fetchone = sessions.get(str(params[0]))
                return
            if normalized.startswith("SELECT data_json FROM focus_agent_team_sessions WHERE user_id"):
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
            if normalized.startswith("SELECT data_json FROM focus_agent_team_tasks WHERE session_id"):
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
            if normalized.startswith("SELECT data_json FROM focus_agent_team_outputs WHERE task_id"):
                self._fetchall = [
                    value
                    for value in outputs.values()
                    if value["data_json"]["task_id"] == params[0]
                ]

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
    assert repo.get_task("task-1").changed_files == [
        "src/focus_agent/repositories/postgres_agent_team_repository.py"
    ]
    assert [item.task_id for item in repo.list_tasks(session_id="session-1")] == ["task-1"]
    assert repo.list_task_outputs(task_id="task-1")[0].test_evidence == [
        "pytest tests/test_postgres_agent_team_repository.py"
    ]
    assert any("CREATE TABLE IF NOT EXISTS focus_agent_team_sessions" in sql for sql in executed)


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
