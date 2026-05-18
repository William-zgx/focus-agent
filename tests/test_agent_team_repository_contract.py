from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from uuid import uuid4

import pytest

from focus_agent.core.agent_team import (
    AgentTeamArtifactKind,
    AgentTeamSession,
    AgentTeamSessionStatus,
    AgentTeamTask,
    AgentTeamTaskOutput,
    AgentTeamTaskRole,
    AgentTeamTaskStatus,
)
from focus_agent.repositories.agent_team_repository import (
    AgentTeamRepository,
    InMemoryAgentTeamRepository,
)
from focus_agent.repositories.postgres_agent_team_repository import PostgresAgentTeamRepository
from focus_agent.repositories.sqlite_agent_team_repository import SQLiteAgentTeamRepository

RepositoryFactory = Callable[[], AgentTeamRepository]


def _session(
    *,
    session_id: str,
    user_id: str = "user-1",
    root_thread_id: str = "root-1",
    created_at: str = "2026-04-25T10:00:00+00:00",
    status: AgentTeamSessionStatus = AgentTeamSessionStatus.PLANNING,
) -> AgentTeamSession:
    return AgentTeamSession(
        session_id=session_id,
        root_thread_id=root_thread_id,
        user_id=user_id,
        title=f"Team {session_id}",
        goal="Exercise repository contract",
        status=status,
        created_at=created_at,
        updated_at=created_at,
    )


def _task(
    *,
    task_id: str,
    session_id: str,
    created_at: str = "2026-04-25T10:01:00+00:00",
    status: AgentTeamTaskStatus = AgentTeamTaskStatus.PENDING,
) -> AgentTeamTask:
    return AgentTeamTask(
        task_id=task_id,
        session_id=session_id,
        branch_id=f"branch-{task_id}",
        child_thread_id=f"child-{task_id}",
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal=f"Implement {task_id}",
        scope=["src/focus_agent/repositories"],
        dependencies=[],
        status=status,
        changed_files=[],
        created_at=created_at,
        updated_at=created_at,
    )


def _output(
    *,
    output_id: str,
    task_id: str,
    created_at: str = "2026-04-25T10:02:00+00:00",
    summary: str | None = None,
) -> AgentTeamTaskOutput:
    return AgentTeamTaskOutput(
        output_id=output_id,
        task_id=task_id,
        kind=AgentTeamArtifactKind.TEST_REPORT,
        artifact_id=f"artifact-{output_id}",
        summary=summary or f"Output {output_id}",
        changed_files=["tests/test_agent_team_repository_contract.py"],
        test_evidence=["pytest tests/test_agent_team_repository_contract.py"],
        risk_notes=[],
        metadata={"output_id": output_id, "passed": True},
        created_at=created_at,
    )


@pytest.fixture(params=["memory", "sqlite", "postgres"])
def agent_team_repo_factory(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Iterator[RepositoryFactory]:
    backend = str(request.param)
    if backend == "memory":
        repo = InMemoryAgentTeamRepository()

        def factory() -> AgentTeamRepository:
            return repo

        yield factory
        return

    if backend == "sqlite":
        db_path = tmp_path / "agent-team.sqlite3"

        def factory() -> AgentTeamRepository:
            return SQLiteAgentTeamRepository(str(db_path))

        yield factory
        return

    database_uri = os.environ.get("DATABASE_URI")
    if not database_uri:
        pytest.skip("DATABASE_URI is required for Postgres agent team repository contract tests")

    schema_suffix = f"contract_agent_team_{uuid4().hex}"
    admin_uri = database_uri
    query_separator = "&" if "?" in database_uri else "?"
    repo_uri = f"{database_uri}{query_separator}options=-csearch_path%3D{schema_suffix}"

    import psycopg

    with psycopg.connect(admin_uri, autocommit=True) as conn:
        conn.execute(f'CREATE SCHEMA "{schema_suffix}"')
    try:
        repo = PostgresAgentTeamRepository(repo_uri)
        repo.setup()

        def factory() -> AgentTeamRepository:
            return PostgresAgentTeamRepository(repo_uri)

        yield factory
    finally:
        with psycopg.connect(admin_uri, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema_suffix}" CASCADE')


def test_agent_team_repository_contract_round_trips_session_task_and_output(
    agent_team_repo_factory: RepositoryFactory,
) -> None:
    repo = agent_team_repo_factory()

    session = _session(session_id="session-1")
    task = _task(task_id="task-1", session_id=session.session_id)
    output = _output(output_id="output-1", task_id=task.task_id)

    repo.create_session(session)
    repo.create_task(task)
    repo.add_task_output(output)

    assert repo.get_session(session.session_id) == session
    assert repo.get_task(task.task_id) == task
    assert repo.list_tasks(session_id=session.session_id) == [task]
    assert repo.list_task_outputs(task_id=task.task_id) == [output]


def test_agent_team_repository_contract_upserts_models_and_replaces_output_payload(
    agent_team_repo_factory: RepositoryFactory,
) -> None:
    repo = agent_team_repo_factory()
    session = _session(session_id="session-upsert")
    task = _task(task_id="task-upsert", session_id=session.session_id)
    output = _output(output_id="output-upsert", task_id=task.task_id, summary="first")

    repo.create_session(session)
    repo.create_task(task)
    repo.add_task_output(output)

    updated_session = session.model_copy(
        update={
            "title": "Renamed team",
            "status": AgentTeamSessionStatus.AWAITING_REVIEW,
            "updated_at": "2026-04-25T11:00:00+00:00",
            "latest_merge_bundle": {
                "session_id": session.session_id,
                "recommended_next_action": "split_followup",
            },
        }
    )
    updated_task = task.model_copy(
        update={
            "status": AgentTeamTaskStatus.DONE,
            "changed_files": ["src/focus_agent/repositories/sqlite_agent_team_repository.py"],
            "verification_summary": "contract passed",
            "updated_at": "2026-04-25T11:01:00+00:00",
        }
    )
    updated_output = output.model_copy(
        update={
            "summary": "updated",
            "test_evidence": ["pytest -q"],
            "created_at": "2026-04-25T11:02:00+00:00",
        }
    )

    repo.save_session(updated_session)
    repo.save_task(updated_task)
    repo.add_task_output(updated_output)

    assert repo.get_session(session.session_id) == updated_session
    assert repo.get_session(session.session_id).created_at == session.created_at
    assert repo.get_task(task.task_id) == updated_task
    assert repo.list_task_outputs(task_id=task.task_id) == [updated_output]


def test_agent_team_repository_contract_lists_sessions_tasks_and_outputs_in_stable_order(
    agent_team_repo_factory: RepositoryFactory,
) -> None:
    repo = agent_team_repo_factory()
    older = _session(
        session_id="session-older",
        user_id="user-1",
        created_at="2026-04-25T09:00:00+00:00",
    )
    newer = _session(
        session_id="session-newer",
        user_id="user-1",
        created_at="2026-04-25T10:00:00+00:00",
    )
    other_user = _session(
        session_id="session-other",
        user_id="user-2",
        created_at="2026-04-25T11:00:00+00:00",
    )
    repo.create_session(older)
    repo.create_session(newer)
    repo.create_session(other_user)

    first_task = _task(
        task_id="task-a",
        session_id=newer.session_id,
        created_at="2026-04-25T10:01:00+00:00",
    )
    second_task = _task(
        task_id="task-b",
        session_id=newer.session_id,
        created_at="2026-04-25T10:02:00+00:00",
    )
    other_task = _task(
        task_id="task-other",
        session_id=older.session_id,
        created_at="2026-04-25T10:03:00+00:00",
    )
    repo.create_task(second_task)
    repo.create_task(other_task)
    repo.create_task(first_task)

    first_output = _output(
        output_id="output-a",
        task_id=first_task.task_id,
        created_at="2026-04-25T10:04:00+00:00",
    )
    second_output = _output(
        output_id="output-b",
        task_id=first_task.task_id,
        created_at="2026-04-25T10:05:00+00:00",
    )
    repo.add_task_output(second_output)
    repo.add_task_output(first_output)

    assert [item.session_id for item in repo.list_sessions(user_id="user-1")] == [
        "session-newer",
        "session-older",
    ]
    assert [item.session_id for item in repo.list_sessions()] == [
        "session-other",
        "session-newer",
        "session-older",
    ]
    assert [item.task_id for item in repo.list_tasks(session_id=newer.session_id)] == [
        "task-a",
        "task-b",
    ]
    assert [item.output_id for item in repo.list_task_outputs(task_id=first_task.task_id)] == [
        "output-a",
        "output-b",
    ]


def test_agent_team_repository_contract_missing_records_raise_key_error(
    agent_team_repo_factory: RepositoryFactory,
) -> None:
    repo = agent_team_repo_factory()

    with pytest.raises(KeyError, match="missing-session"):
        repo.get_session("missing-session")
    with pytest.raises(KeyError, match="missing-task"):
        repo.get_task("missing-task")

    assert repo.list_tasks(session_id="missing-session") == []
    assert repo.list_task_outputs(task_id="missing-task") == []


def test_agent_team_repository_contract_round_trips_execution_links(
    agent_team_repo_factory: RepositoryFactory,
) -> None:
    repo = agent_team_repo_factory()
    session = _session(session_id="session-execution-links")
    task = _task(task_id="task-execution-links", session_id=session.session_id).model_copy(
        update={
            "status": AgentTeamTaskStatus.RUNNING,
            "agent_run_id": "run-1",
            "delegated_task_id": "delegated-task-1",
            "artifact_ids": ["artifact-1"],
            "execution_status": "completed",
        }
    )

    repo.create_session(session)
    repo.create_task(task)

    loaded = repo.get_task(task.task_id)
    assert loaded.agent_run_id == "run-1"
    assert loaded.delegated_task_id == "delegated-task-1"
    assert loaded.artifact_ids == ["artifact-1"]
    assert loaded.execution_status == "completed"


def test_agent_team_repository_contract_claim_heartbeat_release_roundtrip(
    agent_team_repo_factory: RepositoryFactory,
) -> None:
    repo = agent_team_repo_factory()
    session = _session(session_id="session-claim")
    task = _task(
        task_id="task-claim",
        session_id=session.session_id,
        status=AgentTeamTaskStatus.QUEUED,
    )
    repo.create_session(session)
    repo.create_task(task)

    claimed = repo.claim_task(task_id=task.task_id, owner="worker-a", ttl_seconds=30)

    assert claimed is not None
    assert claimed.status == AgentTeamTaskStatus.RUNNING
    assert claimed.attempt == 1
    assert claimed.claim_token
    assert claimed.claim_owner == "worker-a"
    assert claimed.claimed_until is not None
    assert claimed.heartbeat_at is not None
    assert claimed.started_at is not None
    assert repo.claim_task(task_id=task.task_id, owner="worker-b", ttl_seconds=30) is None

    reloaded_claim = agent_team_repo_factory().get_task(task.task_id)
    assert reloaded_claim.claim_token == claimed.claim_token
    assert reloaded_claim.claim_owner == "worker-a"
    assert reloaded_claim.status == AgentTeamTaskStatus.RUNNING

    assert (
        repo.heartbeat_task_claim(
            task_id=task.task_id,
            claim_token="wrong-token",
            ttl_seconds=30,
        )
        is False
    )
    assert (
        repo.heartbeat_task_claim(
            task_id=task.task_id,
            claim_token=claimed.claim_token or "",
            ttl_seconds=30,
        )
        is True
    )
    heartbeat = repo.get_task(task.task_id)
    assert heartbeat.claim_token == claimed.claim_token
    assert heartbeat.status == AgentTeamTaskStatus.RUNNING
    assert heartbeat.heartbeat_at is not None

    ignored_release = repo.release_task_claim(
        task_id=task.task_id,
        claim_token="wrong-token",
        final_status=AgentTeamTaskStatus.DONE,
    )
    assert ignored_release.claim_token == claimed.claim_token
    assert ignored_release.status == AgentTeamTaskStatus.RUNNING

    released = repo.release_task_claim(
        task_id=task.task_id,
        claim_token=claimed.claim_token or "",
        final_status=AgentTeamTaskStatus.DONE,
    )

    assert released.status == AgentTeamTaskStatus.DONE
    assert released.claim_token is None
    assert released.claim_owner is None
    assert released.claimed_until is None
    assert released.finished_at is not None
    persisted_release = agent_team_repo_factory().get_task(task.task_id)
    assert persisted_release.status == AgentTeamTaskStatus.DONE
    assert persisted_release.claim_token is None


def test_agent_team_repository_contract_expired_claim_cannot_release(
    agent_team_repo_factory: RepositoryFactory,
) -> None:
    repo = agent_team_repo_factory()
    session = _session(session_id="session-expired-claim")
    task = _task(
        task_id="task-expired-claim",
        session_id=session.session_id,
        status=AgentTeamTaskStatus.QUEUED,
    )
    repo.create_session(session)
    repo.create_task(task)
    claimed = repo.claim_task(task_id=task.task_id, owner="worker-a", ttl_seconds=0.001)
    assert claimed is not None
    assert claimed.claim_token
    time.sleep(0.01)

    released = repo.release_task_claim(
        task_id=task.task_id,
        claim_token=claimed.claim_token or "",
        final_status=AgentTeamTaskStatus.DONE,
    )

    assert released.status == AgentTeamTaskStatus.RUNNING
    assert released.claim_token == claimed.claim_token
    assert repo.get_task(task.task_id).status == AgentTeamTaskStatus.RUNNING
