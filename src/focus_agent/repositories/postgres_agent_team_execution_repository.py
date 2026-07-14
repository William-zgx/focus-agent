from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from psycopg.types.json import Jsonb

from focus_agent.core.agent_team import (
    EvidenceRecord,
    TaskCheckpoint,
    TaskRun,
    TaskRunEvent,
    ToolExecution,
)

_EXECUTION_RECORD_KEY = "_focus_agent_execution_record"
_TOOL_EXECUTION_EVENT_TYPE = "_focus_agent_tool_execution"


class PostgresAgentTeamExecutionRepositoryMixin:
    """Durable V2 execution records for a Postgres Agent Team repository.

    The host supplies the connection and shared Agent Team ownership helpers.
    Keeping that dependency duck-typed avoids a runtime import cycle with the
    public Postgres repository facade.
    """

    @staticmethod
    def _decode_execution_payload(value: object) -> dict[str, Any]:
        if isinstance(value, str):
            return json.loads(value)
        if isinstance(value, dict):
            return value
        return dict(value)  # type: ignore[arg-type]

    @classmethod
    def _execution_record_payload(
        cls,
        value: TaskRun | TaskCheckpoint | ToolExecution | EvidenceRecord | TaskRunEvent,
    ) -> dict[str, Any]:
        return {_EXECUTION_RECORD_KEY: value.model_dump(mode="json")}

    @classmethod
    def _execution_record_from_row(
        cls,
        row: dict[str, object],
        *,
        field: str,
        model: type[TaskRun]
        | type[TaskCheckpoint]
        | type[ToolExecution]
        | type[EvidenceRecord]
        | type[TaskRunEvent],
    ) -> TaskRun | TaskCheckpoint | ToolExecution | EvidenceRecord | TaskRunEvent:
        container = cls._decode_execution_payload(row[field])
        payload = container.get(_EXECUTION_RECORD_KEY)
        if not isinstance(payload, Mapping):
            raise ValueError(
                f"Postgres agent team execution record in {field} is missing its canonical payload."
            )
        return model.model_validate(dict(payload))

    @classmethod
    def _is_execution_record_row(cls, row: Mapping[str, object], *, field: str) -> bool:
        container = cls._decode_execution_payload(row[field])
        return isinstance(container.get(_EXECUTION_RECORD_KEY), Mapping)

    @classmethod
    def _task_run_from_execution_row(cls, row: dict[str, object]) -> TaskRun:
        value = cls._execution_record_from_row(
            row,
            field="metadata_json",
            model=TaskRun,
        )
        assert isinstance(value, TaskRun)
        return value

    @classmethod
    def _checkpoint_from_execution_row(cls, row: dict[str, object]) -> TaskCheckpoint:
        value = cls._execution_record_from_row(
            row,
            field="metadata_json",
            model=TaskCheckpoint,
        )
        assert isinstance(value, TaskCheckpoint)
        return value

    @classmethod
    def _tool_execution_from_row(cls, row: dict[str, object]) -> ToolExecution:
        value = cls._execution_record_from_row(
            row,
            field="payload_json",
            model=ToolExecution,
        )
        assert isinstance(value, ToolExecution)
        return value

    @classmethod
    def _evidence_from_execution_row(cls, row: dict[str, object]) -> EvidenceRecord:
        value = cls._execution_record_from_row(
            row,
            field="evidence_json",
            model=EvidenceRecord,
        )
        assert isinstance(value, EvidenceRecord)
        return value

    @classmethod
    def _task_run_event_from_row(cls, row: dict[str, object]) -> TaskRunEvent:
        value = cls._execution_record_from_row(
            row,
            field="payload_json",
            model=TaskRunEvent,
        )
        assert isinstance(value, TaskRunEvent)
        return value

    @staticmethod
    def _row_value(row: Mapping[str, object], key: str) -> object:
        return row[key]

    def create_task_run(self, task_run: TaskRun) -> None:
        self._upsert_task_run(task_run)

    def save_task_run(self, task_run: TaskRun) -> None:
        self._upsert_task_run(task_run)

    def _upsert_task_run(self, task_run: TaskRun) -> None:
        requested_attempt_number = int(task_run.attempt or 0)
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._assert_task_owner(
                    cur,
                    task_id=task_run.task_id,
                    session_id=task_run.session_id,
                )
                revision_id = self._persisted_revision_id(
                    cur,
                    session_id=task_run.session_id,
                    revision_id=task_run.revision_id,
                )
                cur.execute(
                    """
                    SELECT attempt_id, session_id, task_id, revision_id, attempt_number,
                           metadata_json
                    FROM focus_agent_team_task_attempts
                    WHERE attempt_id = %s
                    FOR UPDATE
                    """,
                    (task_run.task_run_id,),
                )
                existing_row = cur.fetchone()
                if existing_row is not None:
                    if not self._is_execution_record_row(
                        existing_row,
                        field="metadata_json",
                    ):
                        raise ValueError(
                            f"Agent team task run {task_run.task_run_id} is owned by another "
                            "durable record type."
                        )
                    existing = self._owner_from_task_run_row(existing_row)
                    self._assert_execution_owner(
                        existing,
                        task_run_id=task_run.task_run_id,
                        task_id=task_run.task_id,
                        session_id=task_run.session_id,
                    )
                    attempt_number = int(self._row_value(existing_row, "attempt_number"))
                    if requested_attempt_number > 0 and attempt_number != requested_attempt_number:
                        raise ValueError(
                            f"Task run {task_run.task_run_id} cannot change its durable "
                            "attempt number."
                        )
                else:
                    attempt_number = (
                        requested_attempt_number
                        if requested_attempt_number > 0
                        else self._next_task_attempt_number(cur, task_id=task_run.task_id)
                    )
                    cur.execute(
                        """
                        SELECT attempt_id FROM focus_agent_team_task_attempts
                        WHERE task_id = %s AND attempt_number = %s
                        """,
                        (task_run.task_id, attempt_number),
                    )
                    attempt_row = cur.fetchone()
                    if attempt_row is not None:
                        raise ValueError(
                            f"Task {task_run.task_id} already has durable attempt {attempt_number}."
                        )
                cur.execute(
                    """
                    INSERT INTO focus_agent_team_task_attempts (
                        attempt_id, session_id, task_id, revision_id, attempt_number,
                        status, worker_id, claim_token, input_json, result_json,
                        metadata_json, last_error, started_at, finished_at, created_at, updated_at
                    ) VALUES (
                        %(attempt_id)s, %(session_id)s, %(task_id)s, %(revision_id)s,
                        %(attempt_number)s, %(status)s, NULL, NULL, '{}'::jsonb, '{}'::jsonb,
                        %(metadata_json)s, %(last_error)s, %(started_at)s, %(finished_at)s,
                        %(created_at)s, %(updated_at)s
                    )
                    ON CONFLICT (attempt_id) DO UPDATE SET
                        revision_id = EXCLUDED.revision_id,
                        status = EXCLUDED.status,
                        metadata_json = EXCLUDED.metadata_json,
                        last_error = EXCLUDED.last_error,
                        started_at = EXCLUDED.started_at,
                        finished_at = EXCLUDED.finished_at,
                        updated_at = EXCLUDED.updated_at
                    """,
                    {
                        "attempt_id": task_run.task_run_id,
                        "session_id": task_run.session_id,
                        "task_id": task_run.task_id,
                        "revision_id": revision_id,
                        "attempt_number": attempt_number,
                        "status": task_run.status.value,
                        "metadata_json": Jsonb(self._execution_record_payload(task_run)),
                        "last_error": task_run.last_error,
                        "started_at": task_run.started_at,
                        "finished_at": task_run.finished_at,
                        "created_at": task_run.created_at,
                        "updated_at": task_run.updated_at or task_run.created_at,
                    },
                )

    def get_task_run(self, task_run_id: str) -> TaskRun:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT metadata_json FROM focus_agent_team_task_attempts
                    WHERE attempt_id = %s AND metadata_json ? %s
                    """,
                    (task_run_id, _EXECUTION_RECORD_KEY),
                )
                row = cur.fetchone()
        if row is None:
            raise KeyError(f"Unknown agent team task run: {task_run_id}")
        return self._task_run_from_execution_row(row)

    def list_task_runs(
        self,
        *,
        task_id: str | None = None,
        session_id: str | None = None,
    ) -> list[TaskRun]:
        conditions: list[str] = []
        params: list[str] = []
        if task_id is not None:
            conditions.append("task_id = %s")
            params.append(task_id)
        if session_id is not None:
            conditions.append("session_id = %s")
            params.append(session_id)
        conditions.append("metadata_json ? %s")
        params.append(_EXECUTION_RECORD_KEY)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT metadata_json FROM focus_agent_team_task_attempts
                    {where}
                    ORDER BY created_at, attempt_id
                    """,
                    tuple(params),
                )
                rows = cur.fetchall()
        return sorted(
            (self._task_run_from_execution_row(row) for row in rows),
            key=lambda item: (item.created_at, item.task_run_id),
        )

    def add_task_checkpoint(self, checkpoint: TaskCheckpoint) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                owner = self._task_run_owner(cur, task_run_id=checkpoint.task_run_id)
                assert owner is not None
                self._assert_execution_owner(
                    owner,
                    task_run_id=checkpoint.task_run_id,
                    task_id=checkpoint.task_id,
                    session_id=checkpoint.session_id,
                )
                session_id = str(owner["session_id"])
                task_id = str(owner["task_id"])
                revision_id = self._persisted_revision_id(
                    cur,
                    session_id=session_id,
                    revision_id=checkpoint.revision_id or owner["revision_id"],
                )
                cur.execute(
                    """
                    SELECT session_id, task_id, attempt_id, metadata_json
                    FROM focus_agent_team_checkpoints
                    WHERE checkpoint_id = %s
                    FOR UPDATE
                    """,
                    (checkpoint.checkpoint_id,),
                )
                existing = cur.fetchone()
                if existing is None:
                    checkpoint_sequence = self._next_checkpoint_sequence(
                        cur,
                        session_id=session_id,
                        task_id=task_id,
                    )
                    cur.execute(
                        """
                        INSERT INTO focus_agent_team_checkpoints (
                            checkpoint_id, session_id, task_id, attempt_id, revision_id,
                            checkpoint_kind, checkpoint_sequence, state_json, metadata_json, created_at
                        ) VALUES (
                            %(checkpoint_id)s, %(session_id)s, %(task_id)s, %(attempt_id)s,
                            %(revision_id)s, %(checkpoint_kind)s, %(checkpoint_sequence)s,
                            %(state_json)s, %(metadata_json)s, %(created_at)s
                        )
                        """,
                        {
                            "checkpoint_id": checkpoint.checkpoint_id,
                            "session_id": session_id,
                            "task_id": task_id,
                            "attempt_id": checkpoint.task_run_id,
                            "revision_id": revision_id,
                            "checkpoint_kind": checkpoint.checkpoint_type,
                            "checkpoint_sequence": checkpoint_sequence,
                            "state_json": Jsonb(checkpoint.state),
                            "metadata_json": Jsonb(self._execution_record_payload(checkpoint)),
                            "created_at": checkpoint.created_at,
                        },
                    )
                    return
                if not self._is_execution_record_row(existing, field="metadata_json"):
                    raise ValueError(
                        f"Agent team checkpoint {checkpoint.checkpoint_id} is owned by another "
                        "durable record type."
                    )
                if (
                    self._row_value(existing, "session_id") != session_id
                    or self._row_value(existing, "task_id") != task_id
                    or self._row_value(existing, "attempt_id") != checkpoint.task_run_id
                ):
                    raise ValueError(
                        f"Agent team checkpoint {checkpoint.checkpoint_id} cannot be reassigned "
                        "to a different task run."
                    )
                cur.execute(
                    """
                    UPDATE focus_agent_team_checkpoints
                    SET revision_id = %(revision_id)s,
                        checkpoint_kind = %(checkpoint_kind)s,
                        state_json = %(state_json)s,
                        metadata_json = %(metadata_json)s,
                        created_at = %(created_at)s
                    WHERE checkpoint_id = %(checkpoint_id)s
                    """,
                    {
                        "checkpoint_id": checkpoint.checkpoint_id,
                        "revision_id": revision_id,
                        "checkpoint_kind": checkpoint.checkpoint_type,
                        "state_json": Jsonb(checkpoint.state),
                        "metadata_json": Jsonb(self._execution_record_payload(checkpoint)),
                        "created_at": checkpoint.created_at,
                    },
                )

    def append_task_checkpoint(self, checkpoint: TaskCheckpoint) -> None:
        self.add_task_checkpoint(checkpoint)

    def list_task_checkpoints(self, *, task_run_id: str) -> list[TaskCheckpoint]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._task_run_owner(cur, task_run_id=task_run_id)
                cur.execute(
                    """
                    SELECT metadata_json FROM focus_agent_team_checkpoints
                    WHERE attempt_id = %s AND metadata_json ? %s
                    ORDER BY checkpoint_sequence, created_at, checkpoint_id
                    """,
                    (task_run_id, _EXECUTION_RECORD_KEY),
                )
                rows = cur.fetchall()
        return sorted(
            (self._checkpoint_from_execution_row(row) for row in rows),
            key=lambda item: (item.sequence, item.created_at, item.checkpoint_id),
        )

    def add_tool_execution(self, execution: ToolExecution) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                owner = self._task_run_owner(cur, task_run_id=execution.task_run_id)
                assert owner is not None
                self._assert_execution_owner(
                    owner,
                    task_run_id=execution.task_run_id,
                    task_id=execution.task_id,
                    session_id=execution.session_id,
                )
                self._upsert_execution_event(
                    cur,
                    event_id=execution.tool_execution_id,
                    task_run_id=execution.task_run_id,
                    session_id=str(owner["session_id"]),
                    task_id=str(owner["task_id"]),
                    event_type=_TOOL_EXECUTION_EVENT_TYPE,
                    actor_id=None,
                    payload=self._execution_record_payload(execution),
                    created_at=execution.created_at,
                )

    def append_tool_execution(self, execution: ToolExecution) -> None:
        self.add_tool_execution(execution)

    def list_tool_executions(self, *, task_run_id: str) -> list[ToolExecution]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._task_run_owner(cur, task_run_id=task_run_id)
                cur.execute(
                    """
                    SELECT payload_json FROM focus_agent_team_events
                    WHERE attempt_id = %s
                      AND event_type = %s
                      AND payload_json ? %s
                    ORDER BY created_at, event_id
                    """,
                    (task_run_id, _TOOL_EXECUTION_EVENT_TYPE, _EXECUTION_RECORD_KEY),
                )
                rows = cur.fetchall()
        return sorted(
            (self._tool_execution_from_row(row) for row in rows),
            key=lambda item: (item.created_at, item.tool_execution_id),
        )

    def add_evidence_record(self, evidence: EvidenceRecord) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                attempt_id: str | None = None
                revision_id: str | None = evidence.revision_id
                if evidence.task_run_id is not None:
                    owner = self._task_run_owner(cur, task_run_id=evidence.task_run_id)
                    assert owner is not None
                    self._assert_execution_owner(
                        owner,
                        task_run_id=evidence.task_run_id,
                        task_id=evidence.task_id,
                        session_id=evidence.session_id,
                    )
                    session_id = str(owner["session_id"])
                    task_id = str(owner["task_id"])
                    attempt_id = evidence.task_run_id
                    revision_id = revision_id or owner["revision_id"]
                elif evidence.task_id is not None:
                    session_id = self._task_session_id(cur, task_id=evidence.task_id)
                    if evidence.session_id is not None and evidence.session_id != session_id:
                        raise ValueError(
                            f"Agent team task {evidence.task_id} belongs to session "
                            f"{session_id}, not {evidence.session_id}."
                        )
                    task_id = evidence.task_id
                elif evidence.session_id is not None:
                    self._assert_session_exists(cur, session_id=evidence.session_id)
                    session_id = evidence.session_id
                    task_id = None
                else:
                    raise ValueError(
                        "Durable Agent Team evidence requires a task run, task, or session."
                    )

                cur.execute(
                    """
                    SELECT session_id, task_id, attempt_id, evidence_json
                    FROM focus_agent_team_evidence
                    WHERE evidence_id = %s
                    FOR UPDATE
                    """,
                    (evidence.evidence_id,),
                )
                existing = cur.fetchone()
                if existing is not None and not self._is_execution_record_row(
                    existing,
                    field="evidence_json",
                ):
                    raise ValueError(
                        f"Agent team evidence {evidence.evidence_id} is owned by another "
                        "durable record type."
                    )
                if existing is not None and (
                    self._row_value(existing, "session_id") != session_id
                    or self._row_value(existing, "task_id") != task_id
                    or self._row_value(existing, "attempt_id") != attempt_id
                ):
                    raise ValueError(
                        f"Agent team evidence {evidence.evidence_id} cannot be reassigned "
                        "to a different execution owner."
                    )
                status = (
                    "verified"
                    if evidence.evidence_verdict.value == "verified"
                    else "rejected"
                    if evidence.evidence_verdict.value == "rejected"
                    else "recorded"
                )
                params = {
                    "evidence_id": evidence.evidence_id,
                    "session_id": session_id,
                    "task_id": task_id,
                    "attempt_id": attempt_id,
                    "evidence_kind": evidence.source_type,
                    "status": status,
                    "summary": evidence.summary,
                    "evidence_json": Jsonb(self._execution_record_payload(evidence)),
                    "verification_json": Jsonb(
                        {
                            "evidence_level": evidence.evidence_level.value,
                            "evidence_verdict": evidence.evidence_verdict.value,
                            "revision_id": revision_id,
                        }
                    ),
                    "captured_at": evidence.created_at,
                    "created_at": evidence.created_at,
                }
                if existing is None:
                    cur.execute(
                        """
                        INSERT INTO focus_agent_team_evidence (
                            evidence_id, session_id, task_id, attempt_id, output_id,
                            evidence_kind, status, uri, content_hash, summary, evidence_json,
                            verification_json, captured_at, created_at
                        ) VALUES (
                            %(evidence_id)s, %(session_id)s, %(task_id)s, %(attempt_id)s, NULL,
                            %(evidence_kind)s, %(status)s, NULL, NULL, %(summary)s,
                            %(evidence_json)s, %(verification_json)s, %(captured_at)s,
                            %(created_at)s
                        )
                        """,
                        params,
                    )
                    return
                cur.execute(
                    """
                    UPDATE focus_agent_team_evidence
                    SET evidence_kind = %(evidence_kind)s,
                        status = %(status)s,
                        summary = %(summary)s,
                        evidence_json = %(evidence_json)s,
                        verification_json = %(verification_json)s,
                        captured_at = %(captured_at)s,
                        created_at = %(created_at)s
                    WHERE evidence_id = %(evidence_id)s
                    """,
                    params,
                )

    def append_evidence_record(self, evidence: EvidenceRecord) -> None:
        self.add_evidence_record(evidence)

    def list_evidence_records(
        self,
        *,
        task_run_id: str | None = None,
        task_id: str | None = None,
        session_id: str | None = None,
    ) -> list[EvidenceRecord]:
        conditions: list[str] = []
        params: list[str] = []
        if task_run_id is not None:
            conditions.append("attempt_id = %s")
            params.append(task_run_id)
        if task_id is not None:
            conditions.append("task_id = %s")
            params.append(task_id)
        if session_id is not None:
            conditions.append("session_id = %s")
            params.append(session_id)
        conditions.append("evidence_json ? %s")
        params.append(_EXECUTION_RECORD_KEY)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT evidence_json FROM focus_agent_team_evidence
                    {where}
                    ORDER BY created_at, evidence_id
                    """,
                    tuple(params),
                )
                rows = cur.fetchall()
        return sorted(
            (self._evidence_from_execution_row(row) for row in rows),
            key=lambda item: (item.created_at, item.evidence_id),
        )

    def add_task_run_event(self, event: TaskRunEvent) -> None:
        if event.event_type == _TOOL_EXECUTION_EVENT_TYPE:
            raise ValueError(
                f"{_TOOL_EXECUTION_EVENT_TYPE} is reserved for durable tool executions."
            )
        with self._connect() as conn:
            with conn.cursor() as cur:
                owner = self._task_run_owner(cur, task_run_id=event.task_run_id)
                assert owner is not None
                self._assert_execution_owner(
                    owner,
                    task_run_id=event.task_run_id,
                    task_id=event.task_id,
                    session_id=event.session_id,
                )
                self._upsert_execution_event(
                    cur,
                    event_id=event.event_id,
                    task_run_id=event.task_run_id,
                    session_id=str(owner["session_id"]),
                    task_id=str(owner["task_id"]),
                    event_type=event.event_type,
                    actor_id=None,
                    payload=self._execution_record_payload(event),
                    created_at=event.created_at,
                )

    def append_task_run_event(self, event: TaskRunEvent) -> None:
        self.add_task_run_event(event)

    def list_task_run_events(self, *, task_run_id: str) -> list[TaskRunEvent]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._task_run_owner(cur, task_run_id=task_run_id)
                cur.execute(
                    """
                    SELECT payload_json FROM focus_agent_team_events
                    WHERE attempt_id = %s
                      AND event_type <> %s
                      AND payload_json ? %s
                    ORDER BY created_at, event_id
                    """,
                    (task_run_id, _TOOL_EXECUTION_EVENT_TYPE, _EXECUTION_RECORD_KEY),
                )
                rows = cur.fetchall()
        return sorted(
            (self._task_run_event_from_row(row) for row in rows),
            key=lambda item: (item.created_at, item.event_id),
        )


__all__ = ["PostgresAgentTeamExecutionRepositoryMixin"]
