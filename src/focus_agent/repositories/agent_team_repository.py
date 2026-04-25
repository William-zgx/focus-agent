from __future__ import annotations

from abc import ABC, abstractmethod

from focus_agent.core.agent_team import AgentTeamSession, AgentTeamTask, AgentTeamTaskOutput


class AgentTeamRepository(ABC):
    @abstractmethod
    def create_session(self, session: AgentTeamSession) -> None:
        raise NotImplementedError

    @abstractmethod
    def save_session(self, session: AgentTeamSession) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_session(self, session_id: str) -> AgentTeamSession:
        raise NotImplementedError

    @abstractmethod
    def list_sessions(self, *, user_id: str | None = None) -> list[AgentTeamSession]:
        raise NotImplementedError

    @abstractmethod
    def create_task(self, task: AgentTeamTask) -> None:
        raise NotImplementedError

    @abstractmethod
    def save_task(self, task: AgentTeamTask) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_task(self, task_id: str) -> AgentTeamTask:
        raise NotImplementedError

    @abstractmethod
    def list_tasks(self, *, session_id: str) -> list[AgentTeamTask]:
        raise NotImplementedError

    @abstractmethod
    def add_task_output(self, output: AgentTeamTaskOutput) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_task_outputs(self, *, task_id: str) -> list[AgentTeamTaskOutput]:
        raise NotImplementedError


class InMemoryAgentTeamRepository(AgentTeamRepository):
    def __init__(self) -> None:
        self._sessions: dict[str, AgentTeamSession] = {}
        self._tasks: dict[str, AgentTeamTask] = {}
        self._outputs: dict[str, list[AgentTeamTaskOutput]] = {}

    def create_session(self, session: AgentTeamSession) -> None:
        self._sessions[session.session_id] = session

    def save_session(self, session: AgentTeamSession) -> None:
        self._sessions[session.session_id] = session

    def get_session(self, session_id: str) -> AgentTeamSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"Unknown agent team session: {session_id}")
        return session

    def list_sessions(self, *, user_id: str | None = None) -> list[AgentTeamSession]:
        sessions = list(self._sessions.values())
        if user_id is not None:
            sessions = [session for session in sessions if session.user_id == user_id]
        return sessions

    def create_task(self, task: AgentTeamTask) -> None:
        self._tasks[task.task_id] = task
        self._outputs.setdefault(task.task_id, [])

    def save_task(self, task: AgentTeamTask) -> None:
        self._tasks[task.task_id] = task

    def get_task(self, task_id: str) -> AgentTeamTask:
        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(f"Unknown agent team task: {task_id}")
        return task

    def list_tasks(self, *, session_id: str) -> list[AgentTeamTask]:
        return [task for task in self._tasks.values() if task.session_id == session_id]

    def add_task_output(self, output: AgentTeamTaskOutput) -> None:
        self._outputs.setdefault(output.task_id, []).append(output)

    def list_task_outputs(self, *, task_id: str) -> list[AgentTeamTaskOutput]:
        return list(self._outputs.get(task_id, []))


__all__ = ["AgentTeamRepository", "InMemoryAgentTeamRepository"]
