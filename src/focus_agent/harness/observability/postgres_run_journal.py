from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar
from uuid import uuid4

from psycopg.types.json import Jsonb

from focus_agent.repositories._postgres_base import PostgresMixin
from focus_agent.repositories.postgres_schema import ensure_app_postgres_schema_on_connection
from focus_agent.runtime.thread_pool import shared_thread_pool

from ...core.time_utils import utc_now_iso
from ..runtime.recovery import (
    HARNESS_RUN_API_CLAIM_OWNER,
    HARNESS_RUN_API_LEASE_TTL_SECONDS,
    HARNESS_RUN_RECOVERY_KIND,
    REPLAY_SAFE_EXTERNAL_OUTCOMES,
    HarnessRunRecovery,
)
from ..runtime.runs import is_execution_terminal_run_status
from ..streaming import StreamEvent
from .run_journal import (
    JournalEvent,
    JournalRun,
    JournalToolEvent,
    _copy_json,
    _dict_data,
    _event_id,
    _limit,
    _snapshot,
    _tool_event_from_journal_event,
    _trajectory_summary,
)

T = TypeVar("T")


class PostgresRunJournal(PostgresMixin):
    """PostgreSQL-backed harness run journal.

    Sequence allocation is serialized per run by ``pg_advisory_xact_lock`` in
    ``append_event``, so no process-wide lock is needed and connections come
    from the shared pool when a provider is configured.
    """

    harness_run_lease_ttl_seconds = HARNESS_RUN_API_LEASE_TTL_SECONDS
    harness_run_heartbeat_interval_seconds = 60.0

    def setup(self) -> None:
        with self._connection() as conn:
            ensure_app_postgres_schema_on_connection(conn)

    async def _run_db(self, operation: Callable[[Any], T]) -> T:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(shared_thread_pool(), self._run_db_sync, operation)

    def _run_db_sync(self, operation: Callable[[Any], T]) -> T:
        with self._connection(dict_row=True) as conn:
            return operation(conn)

    async def put(
        self,
        run_id: str,
        *,
        thread_id: str,
        assistant_id: str | None = None,
        user_id: str | None = None,
        status: str = "pending",
        on_disconnect: str = "cancel",
        multitask_strategy: str = "reject",
        metadata: dict[str, Any] | None = None,
        kwargs: dict[str, Any] | None = None,
        error: str | None = None,
        created_at: str | None = None,
    ) -> None:
        now = created_at or utc_now_iso()

        def operation(conn: Any) -> None:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO focus_harness_runs (
                        run_id, thread_id, assistant_id, user_id, status, on_disconnect,
                        multitask_strategy, metadata_json, kwargs_json, error, created_at,
                        updated_at, completion_json
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '{}'::jsonb
                    )
                    ON CONFLICT (run_id) DO UPDATE SET
                        thread_id = EXCLUDED.thread_id,
                        assistant_id = EXCLUDED.assistant_id,
                        user_id = EXCLUDED.user_id,
                        status = EXCLUDED.status,
                        on_disconnect = EXCLUDED.on_disconnect,
                        multitask_strategy = EXCLUDED.multitask_strategy,
                        metadata_json = EXCLUDED.metadata_json,
                        kwargs_json = EXCLUDED.kwargs_json,
                        error = EXCLUDED.error,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        run_id,
                        thread_id,
                        assistant_id,
                        user_id,
                        status,
                        on_disconnect,
                        multitask_strategy,
                        Jsonb(_copy_json(metadata or {})),
                        Jsonb(_copy_json(kwargs or {})),
                        error,
                        now,
                        now,
                    ),
                )
                job_key = f"{HARNESS_RUN_RECOVERY_KIND}:{run_id}"
                payload = {
                    "run_id": run_id,
                    "external_outcome": str((metadata or {}).get("external_outcome") or "unknown"),
                }
                checkpoint_id = (kwargs or {}).get("checkpoint_id")
                if checkpoint_id is not None:
                    payload["checkpoint_id"] = checkpoint_id
                claim_token = uuid4().hex
                claimed_until = datetime.now(UTC) + timedelta(
                    seconds=HARNESS_RUN_API_LEASE_TTL_SECONDS
                )
                cur.execute(
                    """
                    INSERT INTO focus_background_jobs (
                        job_key, kind, payload, run_at, max_attempts, dedupe_policy,
                        status, attempt, claimed_by, claimed_until, claim_token,
                        last_error, last_heartbeat_at, last_failed_at, dead_lettered_at,
                        idempotency_key, created_at, updated_at, metadata
                    )
                    VALUES (%s, %s, %s, now(), 2, 'skip', 'running', 0, %s, %s, %s, NULL,
                            NULL, NULL, NULL, NULL, %s, now(), now(), '{}'::jsonb)
                    ON CONFLICT (job_key) DO NOTHING
                    """,
                    (
                        job_key,
                        HARNESS_RUN_RECOVERY_KIND,
                        Jsonb(payload),
                        HARNESS_RUN_API_CLAIM_OWNER,
                        claimed_until,
                        claim_token,
                        job_key,
                    ),
                )

        await self._run_db(operation)

    async def update_status(
        self,
        run_id: str,
        status: str,
        *,
        error: str | None = None,
    ) -> None:
        execution_terminal = is_execution_terminal_run_status(status)

        def operation(conn: Any) -> None:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE focus_harness_runs
                    SET status = %s, error = COALESCE(%s, error), updated_at = %s
                    WHERE run_id = %s
                    """,
                    (status, error, utc_now_iso(), run_id),
                )
                if execution_terminal:
                    cur.execute(
                        """
                        UPDATE focus_background_jobs
                        SET status = 'succeeded',
                            claimed_by = NULL,
                            claimed_until = NULL,
                            claim_token = NULL,
                            last_heartbeat_at = now(),
                            updated_at = now()
                        WHERE job_key = %s
                          AND kind = %s
                          AND claimed_by = %s
                          AND status IN ('pending', 'running', 'retrying')
                        """,
                        (
                            f"{HARNESS_RUN_RECOVERY_KIND}:{run_id}",
                            HARNESS_RUN_RECOVERY_KIND,
                            HARNESS_RUN_API_CLAIM_OWNER,
                        ),
                    )

        await self._run_db(operation)

    async def heartbeat_harness_run(
        self,
        run_id: str,
        *,
        ttl_seconds: float,
    ) -> bool:
        claimed_until = datetime.now(UTC) + timedelta(seconds=max(ttl_seconds, 0.001))

        def operation(conn: Any) -> bool:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE focus_background_jobs AS jobs
                    SET claimed_until = %s,
                        last_heartbeat_at = now(),
                        updated_at = now()
                    FROM focus_harness_runs AS runs
                    WHERE jobs.job_key = %s
                      AND jobs.kind = %s
                      AND jobs.claimed_by = %s
                      AND jobs.status = 'running'
                      AND jobs.claimed_until > now()
                      AND runs.run_id = %s
                      AND jobs.payload->>'run_id' = runs.run_id
                      AND runs.status IN ('pending', 'running')
                    RETURNING jobs.job_key
                    """,
                    (
                        claimed_until,
                        f"{HARNESS_RUN_RECOVERY_KIND}:{run_id}",
                        HARNESS_RUN_RECOVERY_KIND,
                        HARNESS_RUN_API_CLAIM_OWNER,
                        run_id,
                    ),
                )
                return cur.fetchone() is not None

        return await self._run_db(operation)

    async def update_run_completion(self, run_id: str, **kwargs: Any) -> None:
        def operation(conn: Any) -> None:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT completion_json FROM focus_harness_runs WHERE run_id = %s FOR UPDATE",
                    (run_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return
                completion = _dict_json(row.get("completion_json"))
                completion.update(_copy_json(kwargs))
                cur.execute(
                    """
                    UPDATE focus_harness_runs
                    SET completion_json = %s, updated_at = %s
                    WHERE run_id = %s
                    """,
                    (Jsonb(completion), utc_now_iso(), run_id),
                )

        await self._run_db(operation)

    async def get_run(self, run_id: str) -> JournalRun | None:
        def operation(conn: Any) -> dict[str, Any] | None:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM focus_harness_runs WHERE run_id = %s", (run_id,))
                return cur.fetchone()

        row = await self._run_db(operation)
        return _row_to_run(row) if row is not None else None

    async def list_runs(self, *, thread_id: str | None = None) -> list[JournalRun]:
        def operation(conn: Any) -> list[dict[str, Any]]:
            with conn.cursor() as cur:
                if thread_id is None:
                    cur.execute("SELECT * FROM focus_harness_runs ORDER BY created_at, run_id")
                else:
                    cur.execute(
                        """
                        SELECT * FROM focus_harness_runs
                        WHERE thread_id = %s
                        ORDER BY created_at, run_id
                        """,
                        (thread_id,),
                    )
                return cur.fetchall()

        rows = await self._run_db(operation)
        return [_row_to_run(row) for row in rows]

    async def list_harness_run_recoveries(
        self,
        *,
        kind: str = HARNESS_RUN_RECOVERY_KIND,
    ) -> list[HarnessRunRecovery]:
        if kind != HARNESS_RUN_RECOVERY_KIND:
            return []

        def operation(conn: Any) -> list[dict[str, Any]]:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        runs.*,
                        jobs.job_key AS recovery_job_key,
                        jobs.status AS recovery_job_status,
                        jobs.attempt AS recovery_attempt,
                        jobs.claim_token AS recovery_claim_token,
                        jobs.claimed_until AS recovery_claimed_until,
                        jobs.idempotency_key AS recovery_idempotency_key,
                        jobs.payload AS recovery_payload
                    FROM focus_harness_runs AS runs
                    JOIN focus_background_jobs AS jobs
                      ON jobs.payload->>'run_id' = runs.run_id
                    WHERE jobs.kind = %s
                    ORDER BY runs.created_at, runs.run_id, jobs.job_key
                    """,
                    (kind,),
                )
                return cur.fetchall()

        rows = await self._run_db(operation)
        recoveries: list[HarnessRunRecovery] = []
        for row in rows:
            run = _row_to_run(row)
            payload = _dict_json(row.get("recovery_payload"))
            job_key = str(row.get("recovery_job_key") or "")
            expected_job_key = f"{HARNESS_RUN_RECOVERY_KIND}:{run.run_id}"
            checkpoint_id = _optional_str(payload.get("checkpoint_id"))
            external_outcome = str(payload.get("external_outcome") or "unknown")
            job_status = str(row.get("recovery_job_status") or "unknown")
            attempt = int(row.get("recovery_attempt") or 0)
            requires_reconciliation = (
                job_key != expected_job_key
                or row.get("recovery_idempotency_key") != expected_job_key
                or job_status not in {"pending", "running", "retrying"}
            )
            recoveries.append(
                HarnessRunRecovery(
                    run_id=run.run_id,
                    thread_id=run.thread_id,
                    job_id=job_key,
                    assistant_id=run.assistant_id,
                    user_id=run.user_id,
                    status=run.status,
                    on_disconnect=run.on_disconnect,
                    multitask_strategy=run.multitask_strategy,
                    metadata=run.metadata,
                    kwargs=run.kwargs,
                    error=run.error,
                    created_at=run.created_at,
                    updated_at=run.updated_at,
                    attempt=attempt,
                    job_status=job_status,
                    checkpoint_id=checkpoint_id,
                    claim_token=_optional_str(row.get("recovery_claim_token")),
                    claim_expires_at=row.get("recovery_claimed_until"),
                    requires_reconciliation=requires_reconciliation,
                    external_outcome=external_outcome,
                )
            )
        return recoveries

    async def requeue_harness_run(
        self,
        *,
        run_id: str,
        job_id: str,
        claim_token: str | None,
    ) -> bool | None:
        if claim_token is None:
            return False
        if job_id != f"{HARNESS_RUN_RECOVERY_KIND}:{run_id}":
            return None

        def operation(conn: Any) -> bool | None:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE focus_background_jobs
                    SET status = 'retrying',
                        run_at = now(),
                        claimed_by = NULL,
                        claimed_until = NULL,
                        claim_token = NULL,
                        last_error = 'claim expired before completion',
                        last_failed_at = now(),
                        updated_at = now()
                    WHERE job_key = %s
                      AND kind = %s
                      AND idempotency_key = job_key
                      AND payload->>'run_id' = %s
                      AND EXISTS (
                          SELECT 1 FROM focus_harness_runs AS runs
                          WHERE runs.run_id = focus_background_jobs.payload->>'run_id'
                            AND (
                                runs.status = 'pending'
                                OR (
                                    runs.status = 'running'
                                    AND focus_background_jobs.payload->>'external_outcome' = ANY(%s)
                                )
                            )
                      )
                      AND status = 'running'
                      AND claim_token = %s
                      AND claimed_until IS NOT NULL
                      AND claimed_until <= now()
                      AND attempt < max_attempts
                    RETURNING job_key
                    """,
                    (
                        job_id,
                        HARNESS_RUN_RECOVERY_KIND,
                        run_id,
                        sorted(REPLAY_SAFE_EXTERNAL_OUTCOMES),
                        claim_token,
                    ),
                )
                if cur.fetchone() is not None:
                    return True
                cur.execute(
                    """
                    SELECT (
                        status IN ('pending', 'retrying')
                        OR (status = 'running' AND claimed_until > now())
                    ) AS active
                    FROM focus_background_jobs
                    WHERE job_key = %s
                      AND kind = %s
                      AND idempotency_key = job_key
                      AND payload->>'run_id' = %s
                    """,
                    (job_id, HARNESS_RUN_RECOVERY_KIND, run_id),
                )
                row = cur.fetchone()
                return False if row is not None and row["active"] else None

        return await self._run_db(operation)

    async def append_event(
        self,
        run_id: str,
        event: str,
        data: dict[str, Any] | None = None,
        *,
        event_id: str | None = None,
        stream_event_id: str | None = None,
        sequence: int | None = None,
        created_at: str | None = None,
    ) -> JournalEvent:
        payload = _copy_json(data or {})

        def operation(conn: Any) -> JournalEvent:
            with conn.cursor() as cur:
                effective_sequence = sequence
                if effective_sequence is None:
                    cur.execute(
                        "SELECT pg_advisory_xact_lock(hashtext(%s), 0)",
                        (run_id,),
                    )
                    cur.execute(
                        """
                        SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence
                        FROM focus_harness_run_events
                        WHERE run_id = %s
                        """,
                        (run_id,),
                    )
                    effective_sequence = int(cur.fetchone()["sequence"])
                entry = JournalEvent(
                    event_id=event_id or _event_id(),
                    run_id=run_id,
                    event=event,
                    data=payload,
                    sequence=effective_sequence,
                    stream_event_id=stream_event_id,
                    created_at=created_at or utc_now_iso(),
                )
                cur.execute(
                    """
                    INSERT INTO focus_harness_run_events (
                        event_id, run_id, event, data_json, sequence,
                        stream_event_id, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        entry.event_id,
                        entry.run_id,
                        entry.event,
                        Jsonb(entry.data),
                        entry.sequence,
                        entry.stream_event_id,
                        entry.created_at,
                    ),
                )
                tool_event = _tool_event_from_journal_event(entry)
                if tool_event is not None:
                    cur.execute(
                        """
                        INSERT INTO focus_harness_tool_events (
                            event_id, run_id, tool_call_id, tool_name, status, sequence,
                            args_json, result_json, error, duration_ms, metadata_json,
                            created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            tool_event.event_id,
                            tool_event.run_id,
                            tool_event.tool_call_id,
                            tool_event.tool_name,
                            tool_event.status,
                            tool_event.sequence,
                            Jsonb(tool_event.args),
                            Jsonb(_copy_json(tool_event.result)),
                            tool_event.error,
                            tool_event.duration_ms,
                            Jsonb(tool_event.metadata),
                            tool_event.created_at,
                        ),
                    )
                return entry

        return await self._run_db(operation)

    async def append_stream_event(self, run_id: str, event: StreamEvent) -> JournalEvent:
        return await self.append_event(
            run_id,
            event.event,
            _dict_data(event.data),
            stream_event_id=event.id,
        )

    async def list_events(
        self,
        run_id: str,
        *,
        event: str | None = None,
        limit: int | None = None,
    ) -> list[JournalEvent]:
        def operation(conn: Any) -> list[dict[str, Any]]:
            with conn.cursor() as cur:
                if event is None:
                    cur.execute(
                        """
                        SELECT * FROM focus_harness_run_events
                        WHERE run_id = %s
                        ORDER BY sequence, created_at
                        """,
                        (run_id,),
                    )
                else:
                    cur.execute(
                        """
                        SELECT * FROM focus_harness_run_events
                        WHERE run_id = %s AND event = %s
                        ORDER BY sequence, created_at
                        """,
                        (run_id, event),
                    )
                return cur.fetchall()

        rows = await self._run_db(operation)
        return _limit([_row_to_event(row) for row in rows], limit)

    async def count_events(self, run_id: str, *, event: str | None = None) -> int:
        def operation(conn: Any) -> dict[str, Any]:
            with conn.cursor() as cur:
                if event is None:
                    cur.execute(
                        "SELECT COUNT(*) AS count FROM focus_harness_run_events WHERE run_id = %s",
                        (run_id,),
                    )
                else:
                    cur.execute(
                        """
                        SELECT COUNT(*) AS count
                        FROM focus_harness_run_events
                        WHERE run_id = %s AND event = %s
                        """,
                        (run_id, event),
                    )
                return cur.fetchone()

        row = await self._run_db(operation)
        return int(row["count"])

    async def list_tool_events(
        self,
        run_id: str,
        *,
        tool_name: str | None = None,
        limit: int | None = None,
    ) -> list[JournalToolEvent]:
        def operation(conn: Any) -> list[dict[str, Any]]:
            with conn.cursor() as cur:
                if tool_name is None:
                    cur.execute(
                        """
                        SELECT * FROM focus_harness_tool_events
                        WHERE run_id = %s
                        ORDER BY sequence, created_at
                        """,
                        (run_id,),
                    )
                else:
                    cur.execute(
                        """
                        SELECT * FROM focus_harness_tool_events
                        WHERE run_id = %s AND tool_name = %s
                        ORDER BY sequence, created_at
                        """,
                        (run_id, tool_name),
                    )
                return cur.fetchall()

        rows = await self._run_db(operation)
        return _limit([_row_to_tool_event(row) for row in rows], limit)

    async def count_tool_events(self, run_id: str, *, tool_name: str | None = None) -> int:
        return len(await self.list_tool_events(run_id, tool_name=tool_name))

    async def snapshot(self, run_id: str) -> dict[str, Any]:
        run = await self.get_run(run_id)
        events = await self.list_events(run_id)
        tool_events = await self.list_tool_events(run_id)
        return _snapshot(run, events, tool_events)

    async def trajectory_summary(self, run_id: str) -> dict[str, Any]:
        return _trajectory_summary(await self.snapshot(run_id))


def _row_to_run(row: dict[str, Any]) -> JournalRun:
    return JournalRun(
        run_id=str(row["run_id"]),
        thread_id=str(row["thread_id"]),
        assistant_id=_optional_str(row.get("assistant_id")),
        user_id=_optional_str(row.get("user_id")),
        status=str(row["status"]),
        on_disconnect=str(row.get("on_disconnect") or "cancel"),
        multitask_strategy=str(row["multitask_strategy"]),
        metadata=_dict_json(row.get("metadata_json")),
        kwargs=_dict_json(row.get("kwargs_json")),
        error=_optional_str(row.get("error")),
        created_at=_iso(row.get("created_at")),
        updated_at=_iso(row.get("updated_at")),
        completion=_dict_json(row.get("completion_json")),
    )


def _row_to_event(row: dict[str, Any]) -> JournalEvent:
    return JournalEvent(
        event_id=str(row["event_id"]),
        run_id=str(row["run_id"]),
        event=str(row["event"]),
        data=_dict_json(row.get("data_json")),
        sequence=int(row["sequence"]),
        stream_event_id=_optional_str(row.get("stream_event_id")),
        created_at=_iso(row.get("created_at")),
    )


def _row_to_tool_event(row: dict[str, Any]) -> JournalToolEvent:
    return JournalToolEvent(
        event_id=str(row["event_id"]),
        run_id=str(row["run_id"]),
        tool_call_id=_optional_str(row.get("tool_call_id")),
        tool_name=_optional_str(row.get("tool_name")),
        status=str(row["status"]),
        sequence=int(row["sequence"]),
        args=_dict_json(row.get("args_json")),
        result=row.get("result_json"),
        error=_optional_str(row.get("error")),
        duration_ms=_optional_float(row.get("duration_ms")),
        metadata=_dict_json(row.get("metadata_json")),
        created_at=_iso(row.get("created_at")),
    )


def _dict_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if value is None:
        return {}
    return {"value": _copy_json(value)}


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


__all__ = ["PostgresRunJournal"]
