from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from threading import RLock
from uuid import uuid4

from focus_agent.core.agent_team import (
    AgentTeamMergeReview,
    AgentTeamMergeReviewEvent,
    AgentTeamSession,
    AgentTeamTask,
    AgentTeamTaskOutput,
    AgentTeamTaskStatus,
    EvidenceRecord,
    TaskCheckpoint,
    TaskRun,
    TaskRunEvent,
    ToolExecution,
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

    def save_tasks_bulk(self, tasks: list[AgentTeamTask]) -> None:
        for task in tasks:
            self.save_task(task)

    @abstractmethod
    def get_task(self, task_id: str) -> AgentTeamTask:
        raise NotImplementedError

    @abstractmethod
    def list_tasks(self, *, session_id: str) -> list[AgentTeamTask]:
        raise NotImplementedError

    def claim_task(self, *, task_id: str, owner: str, ttl_seconds: float) -> AgentTeamTask | None:
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

    def heartbeat_task_claim(self, *, task_id: str, claim_token: str, ttl_seconds: float) -> bool:
        task = self.get_task(task_id)
        now = _now()
        if task.claim_token != claim_token or (
            task.claimed_until and _parse_time(task.claimed_until) <= now
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
        if task.claim_token != claim_token or (
            task.claimed_until and _parse_time(task.claimed_until) <= now_dt
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

    # V2 execution records default to per-repository in-memory storage. This keeps
    # existing durable repositories compatible until they opt into persistence.
    def create_task_run(self, task_run: TaskRun) -> None:
        with self._execution_record_lock():
            self._execution_records()["task_runs"][task_run.task_run_id] = task_run

    def save_task_run(self, task_run: TaskRun) -> None:
        self.create_task_run(task_run)

    def get_task_run(self, task_run_id: str) -> TaskRun:
        with self._execution_record_lock():
            task_run = self._execution_records()["task_runs"].get(task_run_id)
        if task_run is None:
            raise KeyError(f"Unknown agent team task run: {task_run_id}")
        return task_run

    def list_task_runs(
        self,
        *,
        task_id: str | None = None,
        session_id: str | None = None,
    ) -> list[TaskRun]:
        with self._execution_record_lock():
            task_runs = list(self._execution_records()["task_runs"].values())
        if task_id is not None:
            task_runs = [item for item in task_runs if item.task_id == task_id]
        if session_id is not None:
            task_runs = [item for item in task_runs if item.session_id == session_id]
        return sorted(task_runs, key=lambda item: (item.created_at, item.task_run_id))

    def add_task_checkpoint(self, checkpoint: TaskCheckpoint) -> None:
        self._append_execution_record("task_checkpoints", checkpoint.checkpoint_id, checkpoint)

    def append_task_checkpoint(self, checkpoint: TaskCheckpoint) -> None:
        self.add_task_checkpoint(checkpoint)

    def list_task_checkpoints(self, *, task_run_id: str) -> list[TaskCheckpoint]:
        with self._execution_record_lock():
            checkpoints = list(self._execution_records()["task_checkpoints"].values())
        return sorted(
            (item for item in checkpoints if item.task_run_id == task_run_id),
            key=lambda item: (item.sequence, item.created_at, item.checkpoint_id),
        )

    def add_tool_execution(self, execution: ToolExecution) -> None:
        self._append_execution_record(
            "tool_executions",
            execution.tool_execution_id,
            execution,
        )

    def append_tool_execution(self, execution: ToolExecution) -> None:
        self.add_tool_execution(execution)

    def list_tool_executions(self, *, task_run_id: str) -> list[ToolExecution]:
        with self._execution_record_lock():
            executions = list(self._execution_records()["tool_executions"].values())
        return sorted(
            (item for item in executions if item.task_run_id == task_run_id),
            key=lambda item: (item.created_at, item.tool_execution_id),
        )

    def add_evidence_record(self, evidence: EvidenceRecord) -> None:
        self._append_execution_record("evidence_records", evidence.evidence_id, evidence)

    def append_evidence_record(self, evidence: EvidenceRecord) -> None:
        self.add_evidence_record(evidence)

    def list_evidence_records(
        self,
        *,
        task_run_id: str | None = None,
        task_id: str | None = None,
        session_id: str | None = None,
    ) -> list[EvidenceRecord]:
        with self._execution_record_lock():
            evidence_records = list(self._execution_records()["evidence_records"].values())
        if task_run_id is not None:
            evidence_records = [
                item for item in evidence_records if item.task_run_id == task_run_id
            ]
        if task_id is not None:
            evidence_records = [item for item in evidence_records if item.task_id == task_id]
        if session_id is not None:
            evidence_records = [item for item in evidence_records if item.session_id == session_id]
        return sorted(evidence_records, key=lambda item: (item.created_at, item.evidence_id))

    def add_task_run_event(self, event: TaskRunEvent) -> None:
        self._append_execution_record("task_run_events", event.event_id, event)

    def append_task_run_event(self, event: TaskRunEvent) -> None:
        self.add_task_run_event(event)

    def list_task_run_events(self, *, task_run_id: str) -> list[TaskRunEvent]:
        with self._execution_record_lock():
            events = list(self._execution_records()["task_run_events"].values())
        return sorted(
            (item for item in events if item.task_run_id == task_run_id),
            key=lambda item: (item.created_at, item.event_id),
        )

    def _append_execution_record(self, collection: str, record_id: str, record: object) -> None:
        with self._execution_record_lock():
            self._execution_records()[collection][record_id] = record

    def _execution_records(self) -> dict[str, dict[str, object]]:
        records = getattr(self, "_agent_team_execution_records", None)
        if records is None:
            records = {
                "task_runs": {},
                "task_checkpoints": {},
                "tool_executions": {},
                "evidence_records": {},
                "task_run_events": {},
            }
            self._agent_team_execution_records = records
        return records

    def _execution_record_lock(self) -> RLock:
        lock = getattr(self, "_agent_team_execution_record_lock", None)
        if lock is None:
            lock = RLock()
            self._agent_team_execution_record_lock = lock
        return lock

    @abstractmethod
    def add_task_output(self, output: AgentTeamTaskOutput) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_task_outputs(self, *, task_id: str) -> list[AgentTeamTaskOutput]:
        raise NotImplementedError

    @abstractmethod
    def save_merge_review(self, review: AgentTeamMergeReview) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_merge_review(self, review_id: str) -> AgentTeamMergeReview:
        raise NotImplementedError

    @abstractmethod
    def list_merge_reviews(self, *, session_id: str) -> list[AgentTeamMergeReview]:
        raise NotImplementedError

    @abstractmethod
    def add_merge_review_event(self, event: AgentTeamMergeReviewEvent) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_merge_review_events(self, *, review_id: str) -> list[AgentTeamMergeReviewEvent]:
        raise NotImplementedError


class InMemoryAgentTeamRepository(AgentTeamRepository):
    def __init__(self) -> None:
        self._lock = RLock()
        self._sessions: dict[str, AgentTeamSession] = {}
        self._tasks: dict[str, AgentTeamTask] = {}
        self._outputs: dict[str, list[AgentTeamTaskOutput]] = {}
        self._merge_reviews: dict[str, AgentTeamMergeReview] = {}
        self._merge_review_events: dict[str, list[AgentTeamMergeReviewEvent]] = {}

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

    def save_tasks_bulk(self, tasks: list[AgentTeamTask]) -> None:
        if not tasks:
            return
        with self._lock:
            for task in tasks:
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

    def claim_task(self, *, task_id: str, owner: str, ttl_seconds: float) -> AgentTeamTask | None:
        with self._lock:
            return super().claim_task(task_id=task_id, owner=owner, ttl_seconds=ttl_seconds)

    def heartbeat_task_claim(self, *, task_id: str, claim_token: str, ttl_seconds: float) -> bool:
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

    def save_merge_review(self, review: AgentTeamMergeReview) -> None:
        with self._lock:
            self._merge_reviews[review.review_id] = review
            self._merge_review_events.setdefault(review.review_id, [])

    def get_merge_review(self, review_id: str) -> AgentTeamMergeReview:
        with self._lock:
            review = self._merge_reviews.get(review_id)
        if review is None:
            raise KeyError(f"Unknown agent team merge review: {review_id}")
        return review

    def list_merge_reviews(self, *, session_id: str) -> list[AgentTeamMergeReview]:
        with self._lock:
            reviews = [
                review for review in self._merge_reviews.values() if review.session_id == session_id
            ]
        return sorted(reviews, key=lambda item: (item.created_at, item.review_id), reverse=True)

    def add_merge_review_event(self, event: AgentTeamMergeReviewEvent) -> None:
        with self._lock:
            events = [
                existing
                for existing in self._merge_review_events.setdefault(event.review_id, [])
                if existing.event_id != event.event_id
            ]
            events.append(event)
            self._merge_review_events[event.review_id] = events

    def list_merge_review_events(self, *, review_id: str) -> list[AgentTeamMergeReviewEvent]:
        with self._lock:
            events = list(self._merge_review_events.get(review_id, []))
        return sorted(events, key=lambda item: (item.created_at, item.event_id))


__all__ = ["AgentTeamRepository", "InMemoryAgentTeamRepository"]


def _now() -> datetime:
    return datetime.now(UTC)


def _format_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
