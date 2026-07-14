from __future__ import annotations

from focus_agent.core.agent_team import EvidenceRecord, TaskRun
from focus_agent.services.agent_team_merge import *
from focus_agent.services.agent_team_merge import __all__ as _agent_team_merge_all
from focus_agent.services.agent_team_run import *
from focus_agent.services.agent_team_run import AgentTeamRunMixin as _AgentTeamRunMixin
from focus_agent.services.agent_team_run import __all__ as _agent_team_run_all


class AgentTeamRunMixin(_AgentTeamRunMixin):
    def agent_team_v2_capabilities(self) -> dict[str, bool]:
        """Return the v2 operations that this service can safely perform."""
        return {
            "task_run_queries": True,
            "evidence_queries": True,
            "revision_commands": False,
        }

    def get_task_run(self, *, task_run_id: str, user_id: str) -> TaskRun:
        with self._lock:
            task_run = self.repository.get_task_run(task_run_id)
        task = self.get_task(task_run.task_id, user_id=user_id)
        if task.session_id != task_run.session_id:
            raise KeyError(f"Agent team task run does not match its task: {task_run_id}")
        return task_run

    def list_task_runs(self, *, task_id: str, user_id: str) -> list[TaskRun]:
        task = self.get_task(task_id, user_id=user_id)
        with self._lock:
            task_runs = self.repository.list_task_runs(task_id=task_id)
        return [task_run for task_run in task_runs if task_run.session_id == task.session_id]

    def list_evidence_records(self, *, session_id: str, user_id: str) -> list[EvidenceRecord]:
        self.get_session(session_id, user_id=user_id)
        with self._lock:
            return self.repository.list_evidence_records(session_id=session_id)

    def execute_revision_command(
        self,
        *,
        session_id: str,
        user_id: str,
        command: str,
        revision_id: str | None,
        parent_revision_id: str | None,
        task_ids: list[str],
        metadata: dict[str, object],
    ) -> dict[str, object]:
        self.get_session(session_id, user_id=user_id)
        for task_id in task_ids:
            task = self.get_task(task_id, user_id=user_id)
            if task.session_id != session_id:
                raise ValueError(f"Task does not belong to this session: {task_id}")
        raise NotImplementedError(
            "Agent Team revision commands are not enabled; no revision command was executed."
        )


__all__ = [
    *_agent_team_merge_all,
    *(name for name in _agent_team_run_all if name != "AgentTeamRunMixin"),
    "AgentTeamRunMixin",
]
