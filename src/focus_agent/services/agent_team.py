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
from .agent_team_sessions import AgentTeamSessionTaskMixin


class AgentTeamService(
    AgentTeamSessionTaskMixin,
    AgentTeamDispatchMixin,
    AgentTeamMergeMixin,
    AgentTeamHelperMixin,
):
    """Coordinator facade for Agent Team Workbench sessions."""

    def __init__(
        self,
        *,
        branch_service: BranchService | None = None,
        repository: AgentTeamRepository | None = None,
    ):
        self.branch_service = branch_service
        self.repository = repository or InMemoryAgentTeamRepository()
        self._lock = RLock()


__all__ = [
    "AgentTeamService",
    "_DEFAULT_DISPATCH_TASKS",
    "_ROLE_TO_BRANCH_ROLE",
    "_dedupe",
    "_now",
]
