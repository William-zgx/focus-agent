from __future__ import annotations

from types import SimpleNamespace

from focus_agent.config import Settings
from focus_agent.core.agent_team import (
    AgentTeamFinalAnswerStatus,
    AgentTeamTaskRole,
    AgentTeamTaskStatus,
)
from focus_agent.multi_agent.contracts import LockMode
from focus_agent.multi_agent.message_bus import InMemoryAgentMessageBus
from focus_agent.multi_agent.resource_lock import InMemoryResourceLockManager
from focus_agent.services.agent_team import AgentTeamService


class _QueuedOnlyBackground:
    def __init__(self) -> None:
        self.submitted: list[str] = []

    def submit(self, *, key: str, **kwargs) -> bool:
        self.submitted.append(key)
        return True


def test_agent_team_dag_scheduler_feature_flag_queues_non_conflicting_wave() -> None:
    service = AgentTeamService(
        branch_service=None,
        settings=Settings(
            multi_agent_v2_enabled=True,
            multi_agent_dag_scheduler_enabled=True,
            agent_role_max_parallel_runs=3,
        ),
        background_work=_QueuedOnlyBackground(),
    )
    session = service.create_session(user_id="user-1", goal="Implement split feature")
    design = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.ARCHITECT,
        goal="Design",
        create_branch=False,
    )
    design = service.update_task(
        task_id=design.task_id,
        user_id="user-1",
        status=AgentTeamTaskStatus.DONE,
    )
    backend = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal="Backend",
        dependencies=[design.task_id],
        resource_claims=["file:src/shared.py"],
        create_branch=False,
    )
    frontend = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.FRONTEND_EXECUTOR,
        goal="Frontend",
        dependencies=[design.task_id],
        resource_claims=["file:apps/web.tsx"],
        create_branch=False,
    )
    reviewer = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.REVIEWER,
        goal="Review",
        dependencies=[backend.task_id, frontend.task_id],
        create_branch=False,
    )

    _, tasks = service.run_ready_tasks_once(session_id=session.session_id, user_id="user-1")
    statuses = {task.task_id: task.status for task in tasks}

    assert statuses[backend.task_id] == AgentTeamTaskStatus.QUEUED
    assert statuses[frontend.task_id] == AgentTeamTaskStatus.QUEUED
    assert statuses[reviewer.task_id] == AgentTeamTaskStatus.PENDING


def test_agent_team_merge_marks_blocking_multi_agent_conflict() -> None:
    service = AgentTeamService(
        branch_service=None,
        settings=Settings(multi_agent_v2_enabled=True),
    )
    session = service.create_session(user_id="user-1", goal="Merge conflicted work")
    first = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal="Patch A",
        create_branch=False,
    )
    second = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.FRONTEND_EXECUTOR,
        goal="Patch B",
        create_branch=False,
    )
    service.update_task(task_id=first.task_id, user_id="user-1", status=AgentTeamTaskStatus.DONE)
    service.update_task(task_id=second.task_id, user_id="user-1", status=AgentTeamTaskStatus.DONE)
    service.record_task_output(
        task_id=first.task_id,
        user_id="user-1",
        summary="The shared module should use retries.",
        changed_files=["src/shared.py"],
    )
    service.record_task_output(
        task_id=second.task_id,
        user_id="user-1",
        summary="The shared module should not use retries.",
        changed_files=["src/shared.py"],
    )

    bundle = service.prepare_merge_bundle(session_id=session.session_id, user_id="user-1")

    assert bundle.final_answer_status == AgentTeamFinalAnswerStatus.BLOCKED
    assert bundle.recommended_next_action == "request_changes"
    assert any("Merge conflict blocking" in item for item in bundle.risk_items)


def test_agent_team_progress_messages_publish_when_enabled() -> None:
    bus = InMemoryAgentMessageBus()
    service = AgentTeamService(
        branch_service=None,
        settings=Settings(multi_agent_v2_enabled=True, multi_agent_message_bus_enabled=True),
        coordination_backend=SimpleNamespace(message_bus=bus),
    )
    session = service.create_session(user_id="user-1", goal="Report progress")
    task = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal="Implement",
        create_branch=False,
    )

    service._publish_agent_team_progress(task=task, event="started")

    messages = bus.subscribe(session_id=session.session_id, agent_id="observer").poll()
    assert messages[0].payload["event"] == "started"


def test_agent_team_resource_lock_helper_acquires_and_releases_claims() -> None:
    locks = InMemoryResourceLockManager()
    service = AgentTeamService(
        branch_service=None,
        settings=Settings(multi_agent_v2_enabled=True, multi_agent_resource_lock_enabled=True),
        coordination_backend=SimpleNamespace(resource_locks=locks),
    )
    session = service.create_session(user_id="user-1", goal="Lock resources")
    task = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal="Implement",
        resource_claims=["file:src/shared.py"],
        create_branch=False,
    )

    claims = service._acquire_task_resource_claims(task)

    assert [claim.resource_id for claim in claims] == ["file:src/shared.py"]
    assert locks.list_active_claims() == claims
    service._release_task_resource_claims(claims)
    assert locks.list_active_claims() == []


def test_agent_team_resource_lock_blocks_conflicting_execution() -> None:
    service = AgentTeamService(
        branch_service=None,
        settings=Settings(
            multi_agent_v2_enabled=True,
            multi_agent_resource_lock_enabled=True,
        ),
    )
    session = service.create_session(user_id="user-1", goal="Protect shared file")
    task = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal="Edit shared file",
        resource_claims=["file:src/shared.py"],
        create_branch=False,
    )
    lock_backend = service.coordination_backend.resource_locks
    assert (
        lock_backend.try_acquire(
            resource_id="file:src/shared.py",
            agent_id="backend:other",
            session_id=session.session_id,
            mode=LockMode.EXCLUSIVE,
            ttl_seconds=60,
        )
        is not None
    )

    _, tasks = service.run_ready_tasks_once(session_id=session.session_id, user_id="user-1")
    updated = {item.task_id: item for item in tasks}[task.task_id]

    assert updated.status == AgentTeamTaskStatus.PENDING
    assert updated.execution_status == "waiting_resource_lock"
    assert "resource lock" in (updated.last_error or "")
