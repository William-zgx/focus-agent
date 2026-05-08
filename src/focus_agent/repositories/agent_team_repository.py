from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from threading import RLock
from uuid import uuid4

from focus_agent.core.agent_team import (
    AgentTeamSession,
    AgentTeamTask,
    AgentTeamTaskOutput,
    AgentTeamTaskStatus,
)


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

    def claim_task(
        self, *, task_id: str, owner: str, ttl_seconds: float
    ) -> AgentTeamTask | None:
        task = self.get_task(task_id)
        if task.status not in {AgentTeamTaskStatus.QUEUED, AgentTeamTaskStatus.RUNNING}:
            return None
        now = _now()
        if task.claimed_until and task.claim_token and _parse_time(task.claimed_until) > now:
            return None
        claim_token = uuid4().hex
        updated = task.model_copy(
            update={
                "status": AgentTeamTaskStatus.RUNNING,
                "attempt": max(0, int(task.attempt or 0)) + 1,
                "claim_token": claim_token,
                "claim_owner": str(owner or "agent-team-worker"),
                "claimed_until": _format_time(
                    now + timedelta(seconds=max(float(ttl_seconds or 0.0), 0.001))
                ),
                "heartbeat_at": _format_time(now),
                "started_at": task.started_at or _format_time(now),
                "updated_at": _format_time(now),
            }
        )
        self.save_task(updated)
        return updated

    def heartbeat_task_claim(
        self, *, task_id: str, claim_token: str, ttl_seconds: float
    ) -> bool:
        task = self.get_task(task_id)
        now = _now()
        if (
            task.claim_token != claim_token
            or (task.claimed_until and _parse_time(task.claimed_until) <= now)
        ):
            return False
        updated = task.model_copy(
            update={
                "claimed_until": _format_time(
                    now + timedelta(seconds=max(float(ttl_seconds or 0.0), 0.001))
                ),
                "heartbeat_at": _format_time(now),
                "updated_at": _format_time(now),
            }
        )
        self.save_task(updated)
        return True

    def release_task_claim(
        self,
        *,
        task_id: str,
        claim_token: str,
        final_status: AgentTeamTaskStatus | str,
        error: str | None = None,
    ) -> AgentTeamTask:
        task = self.get_task(task_id)
        now_dt = _now()
        if (
            task.claim_token != claim_token
            or (task.claimed_until and _parse_time(task.claimed_until) <= now_dt)
        ):
            return task
        now = _format_time(now_dt)
        updated = task.model_copy(
            update={
                "status": AgentTeamTaskStatus(final_status),
                "claim_token": None,
                "claim_owner": None,
                "claimed_until": None,
                "heartbeat_at": now,
                "finished_at": now
                if AgentTeamTaskStatus(final_status)
                in {
                    AgentTeamTaskStatus.DONE,
                    AgentTeamTaskStatus.FAILED,
                    AgentTeamTaskStatus.CANCELLED,
                    AgentTeamTaskStatus.BLOCKED,
                }
                else task.finished_at,
                "last_error": error if error is not None else task.last_error,
                "updated_at": now,
            }
        )
        self.save_task(updated)
        return updated

    def list_runnable_tasks(self, *, session_id: str, limit: int) -> list[AgentTeamTask]:
        tasks = self.list_tasks(session_id=session_id)
        done_ids = {task.task_id for task in tasks if task.status == AgentTeamTaskStatus.DONE}
        runnable = [
            task
            for task in tasks
            if (
                task.status == AgentTeamTaskStatus.PENDING
                or (
                    task.status == AgentTeamTaskStatus.RUNNING
                    and not task.run_status
                    and not task.execution_status
                    and not task.agent_run_id
                )
            )
            and all(dependency in done_ids for dependency in task.dependencies)
        ]
        return runnable[: max(0, int(limit or 0))]

    @abstractmethod
    def add_task_output(self, output: AgentTeamTaskOutput) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_task_outputs(self, *, task_id: str) -> list[AgentTeamTaskOutput]:
        raise NotImplementedError


class InMemoryAgentTeamRepository(AgentTeamRepository):
    def __init__(self) -> None:
        self._lock = RLock()
        self._sessions: dict[str, AgentTeamSession] = {}
        self._tasks: dict[str, AgentTeamTask] = {}
        self._outputs: dict[str, list[AgentTeamTaskOutput]] = {}

    def create_session(self, session: AgentTeamSession) -> None:
        with self._lock:
            self._sessions[session.session_id] = session

    def save_session(self, session: AgentTeamSession) -> None:
        with self._lock:
            self._sessions[session.session_id] = session

    def get_session(self, session_id: str) -> AgentTeamSession:
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"Unknown agent team session: {session_id}")
        return session

    def list_sessions(self, *, user_id: str | None = None) -> list[AgentTeamSession]:
        with self._lock:
            sessions = list(self._sessions.values())
        if user_id is not None:
            sessions = [session for session in sessions if session.user_id == user_id]
        return sorted(sessions, key=lambda item: (item.created_at, item.session_id), reverse=True)

    def create_task(self, task: AgentTeamTask) -> None:
        with self._lock:
            self._tasks[task.task_id] = task
            self._outputs.setdefault(task.task_id, [])

    def save_task(self, task: AgentTeamTask) -> None:
        with self._lock:
            self._tasks[task.task_id] = task

    def get_task(self, task_id: str) -> AgentTeamTask:
        with self._lock:
            task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(f"Unknown agent team task: {task_id}")
        return task

    def list_tasks(self, *, session_id: str) -> list[AgentTeamTask]:
        with self._lock:
            tasks = [task for task in self._tasks.values() if task.session_id == session_id]
        return sorted(tasks, key=lambda item: (item.created_at, item.task_id))

    def claim_task(
        self, *, task_id: str, owner: str, ttl_seconds: float
    ) -> AgentTeamTask | None:
        with self._lock:
            return super().claim_task(task_id=task_id, owner=owner, ttl_seconds=ttl_seconds)

    def heartbeat_task_claim(
        self, *, task_id: str, claim_token: str, ttl_seconds: float
    ) -> bool:
        with self._lock:
            return super().heartbeat_task_claim(
                task_id=task_id,
                claim_token=claim_token,
                ttl_seconds=ttl_seconds,
            )

    def release_task_claim(
        self,
        *,
        task_id: str,
        claim_token: str,
        final_status: AgentTeamTaskStatus | str,
        error: str | None = None,
    ) -> AgentTeamTask:
        with self._lock:
            return super().release_task_claim(
                task_id=task_id,
                claim_token=claim_token,
                final_status=final_status,
                error=error,
            )

    def add_task_output(self, output: AgentTeamTaskOutput) -> None:
        with self._lock:
            outputs = [
                existing
                for existing in self._outputs.setdefault(output.task_id, [])
                if existing.output_id != output.output_id
            ]
            outputs.append(output)
            self._outputs[output.task_id] = outputs

    def list_task_outputs(self, *, task_id: str) -> list[AgentTeamTaskOutput]:
        with self._lock:
            outputs = list(self._outputs.get(task_id, []))
        return sorted(outputs, key=lambda item: (item.created_at, item.output_id))


__all__ = ["AgentTeamRepository", "InMemoryAgentTeamRepository"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
