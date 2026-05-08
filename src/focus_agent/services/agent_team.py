from __future__ import annotations

from threading import RLock

from focus_agent.repositories.agent_team_repository import (
    AgentTeamRepository,
    InMemoryAgentTeamRepository,
)
from focus_agent.services.branches import BranchService

from .agent_team_dispatch import AgentTeamDispatchMixin, _DEFAULT_DISPATCH_TASKS
from .agent_team_helpers import AgentTeamHelperMixin, _ROLE_TO_BRANCH_ROLE, _dedupe, _now
from .agent_team_merge import AgentTeamMergeMixin
from .agent_team_planning import AgentTeamPlanningMixin
from .agent_team_run import AgentTeamRunMixin
from .agent_team_sessions import AgentTeamSessionTaskMixin


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
    ):
        self.branch_service = branch_service
        self.repository = repository or InMemoryAgentTeamRepository()
        self.settings = settings
        self.model_factory = model_factory
        self.executor = executor
        self.coordination_backend = coordination_backend
        self.background_work = background_work
        self._lock = RLock()


__all__ = [
    "AgentTeamService",
    "_DEFAULT_DISPATCH_TASKS",
    "_ROLE_TO_BRANCH_ROLE",
    "_dedupe",
    "_now",
]
