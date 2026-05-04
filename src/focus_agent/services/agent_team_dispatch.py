from __future__ import annotations

from focus_agent.core.agent_team import (
    AgentTeamSession,
    AgentTeamTask,
    AgentTeamTaskRole,
    AgentTeamTaskStatus,
)


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
                goal=f"{goal_template}\n\nSession goal: {session.goal}",
                scope=list(scope),
                dependencies=dependencies,
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
        return session, tasks


__all__ = ["AgentTeamDispatchMixin", "_DEFAULT_DISPATCH_TASKS"]
