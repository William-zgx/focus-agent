from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from threading import RLock
from time import perf_counter

from focus_agent.core.agent_team import (
    AgentTeamSession,
    AgentTeamTask,
    AgentTeamTaskRole,
    AgentTeamTaskStatus,
)
from focus_agent.core.time_utils import utc_now_iso
from focus_agent.observability.metrics import AGENT_TEAM_SCHEDULER_LOCK_WAIT_MS
from focus_agent.repositories.agent_team_repository import (
    AgentTeamRepository,
    InMemoryAgentTeamRepository,
)
from focus_agent.services.agent_team.helpers import AgentTeamHelperMixin
from focus_agent.services.agent_team.planning import AgentTeamPlanningMixin
from focus_agent.services.agent_team.run import AgentTeamMergeMixin, AgentTeamRunMixin
from focus_agent.services.agent_team.sessions import AgentTeamSessionTaskMixin
from focus_agent.services.agent_team.workspace import AgentTeamWorkspaceService
from focus_agent.services.branches import BranchService
from focus_agent.services.coordination import create_in_memory_coordination_backend

_DEFAULT_DISPATCH_TASKS: tuple[
    tuple[AgentTeamTaskRole, str, tuple[str, ...], tuple[AgentTeamTaskRole, ...]], ...
] = (
    (
        AgentTeamTaskRole.PLANNER,
        "Plan the work, clarify boundaries, and produce the implementation checklist.",
        ("docs/**", "src/**", "apps/web/**", "frontend-sdk/**", "tests/**"),
        (),
    ),
    (
        AgentTeamTaskRole.BACKEND_EXECUTOR,
        "Implement the backend/API orchestration surface and keep contracts compatible.",
        ("src/focus_agent/**", "tests/**"),
        (AgentTeamTaskRole.PLANNER,),
    ),
    (
        AgentTeamTaskRole.FRONTEND_EXECUTOR,
        "Implement the SDK and Web workbench controls for the orchestration flow.",
        (
            "frontend-sdk/**",
            "apps/web/src/features/agent-team/**",
            "apps/web/src/pages/agent-team/**",
        ),
        (AgentTeamTaskRole.PLANNER,),
    ),
    (
        AgentTeamTaskRole.TEST_ENGINEER,
        "Add and run focused tests that prove the orchestration flow works.",
        ("tests/**", "frontend-sdk/**", "apps/web/**"),
        (AgentTeamTaskRole.BACKEND_EXECUTOR, AgentTeamTaskRole.FRONTEND_EXECUTOR),
    ),
    (
        AgentTeamTaskRole.REVIEWER,
        "Review the coordinated changes for regressions, risk, and missing evidence.",
        ("src/**", "frontend-sdk/**", "apps/web/**", "tests/**"),
        (AgentTeamTaskRole.TEST_ENGINEER,),
    ),
    (
        AgentTeamTaskRole.VERIFIER,
        "Collect final verification evidence and identify remaining release risks.",
        ("tests/**", "docs/**"),
        (AgentTeamTaskRole.REVIEWER,),
    ),
)


class AgentTeamDispatchMixin:
    def dispatch_default_tasks(
        self,
        *,
        session_id: str,
        user_id: str,
        create_branches: bool = True,
        parent_thread_id: str | None = None,
    ) -> tuple[AgentTeamSession, list[AgentTeamTask]]:
        session = self.get_session(session_id, user_id=user_id)
        existing = self.list_tasks(session_id=session_id, user_id=user_id)
        by_role = {task.role: task for task in existing}
        created_by_role: dict[AgentTeamTaskRole, AgentTeamTask] = {}

        for role, goal_template, scope, dependency_roles in _DEFAULT_DISPATCH_TASKS:
            if role in by_role:
                created_by_role[role] = by_role[role]
                continue
            dependencies = [
                created_by_role[dependency_role].task_id
                for dependency_role in dependency_roles
                if dependency_role in created_by_role
            ]
            task = self.create_task(
                session_id=session_id,
                user_id=user_id,
                role=role,
                title=role.value.replace("_", " ").title(),
                goal=f"{goal_template}\n\nSession goal: {session.goal}",
                scope=list(scope),
                dependencies=dependencies,
                planning_rationale="Legacy dispatch template task retained for backwards compatibility.",
                sort_order=len(created_by_role) + 1,
                task_type="coordination" if role == AgentTeamTaskRole.PLANNER else "execution",
                plan_source="legacy_template",
                create_branch=create_branches,
                parent_thread_id=parent_thread_id or session.root_thread_id,
            )
            created_by_role[role] = task

        planner = created_by_role.get(AgentTeamTaskRole.PLANNER)
        if planner and planner.status == AgentTeamTaskStatus.PENDING:
            planner = self.update_task(
                task_id=planner.task_id,
                user_id=user_id,
                status=AgentTeamTaskStatus.RUNNING,
            )
            created_by_role[AgentTeamTaskRole.PLANNER] = planner

        tasks = self.list_tasks(session_id=session_id, user_id=user_id)
        session = self.get_session(session_id, user_id=user_id)
        with self._lock:
            session = session.model_copy(
                update={
                    "planning_source": session.planning_source or "legacy_template",
                    "planning_rationale": session.planning_rationale
                    or "Legacy dispatch template generated the fixed compatibility task set.",
                    "plan_generated_at": session.plan_generated_at or utc_now_iso(),
                    "updated_at": utc_now_iso(),
                }
            )
            self.repository.save_session(session)
        return session, tasks


class AgentTeamService(
    AgentTeamSessionTaskMixin,
    AgentTeamDispatchMixin,
    AgentTeamPlanningMixin,
    AgentTeamRunMixin,
    AgentTeamMergeMixin,
    AgentTeamHelperMixin,
):
    """Coordinator facade for Agent Team Workbench sessions."""

    def __init__(
        self,
        *,
        branch_service: BranchService | None = None,
        repository: AgentTeamRepository | None = None,
        settings: object | None = None,
        model_factory: object | None = None,
        executor: object | None = None,
        coordination_backend: object | None = None,
        background_work: object | None = None,
        workspace_service: AgentTeamWorkspaceService | None = None,
        retrieval_index: object | None = None,
        memory_embedding_provider: object | None = None,
    ):
        self.branch_service = branch_service
        self.repository = repository or InMemoryAgentTeamRepository()
        self.settings = settings
        self.model_factory = model_factory
        self.executor = executor
        self.coordination_backend = coordination_backend or create_in_memory_coordination_backend()
        self.background_work = background_work
        self.workspace_service = workspace_service or AgentTeamWorkspaceService(
            repo_root=getattr(settings, "workspace_root", None)
        )
        self.retrieval_index = retrieval_index
        self.memory_embedding_provider = memory_embedding_provider
        self._lock = RLock()
        self._session_locks_guard = RLock()
        self._session_locks: dict[str, RLock] = {}

    def _lock_for_session(self, session_id: str) -> RLock:
        with self._session_locks_guard:
            lock = self._session_locks.get(session_id)
            if lock is None:
                lock = RLock()
                self._session_locks[session_id] = lock
            return lock

    @contextmanager
    def _scheduler_lock(self, session_id: str) -> Iterator[None]:
        start = perf_counter()
        lock = self._lock_for_session(session_id)
        lock.acquire()
        wait_ms = (perf_counter() - start) * 1000.0
        AGENT_TEAM_SCHEDULER_LOCK_WAIT_MS.record(wait_ms, {"session_id": session_id})
        try:
            yield
        finally:
            lock.release()


__all__ = [
    "AgentTeamDispatchMixin",
    "AgentTeamService",
    "_DEFAULT_DISPATCH_TASKS",
]
