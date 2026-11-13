from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("focus_agent.harness.runtime")

HARNESS_RUN_RECOVERY_KIND = "harness_run"
HARNESS_RUN_API_CLAIM_OWNER = "api"
HARNESS_RUN_API_LEASE_TTL_SECONDS = 300.0


REPLAY_SAFE_EXTERNAL_OUTCOMES = frozenset({"replay_safe", "reconciled"})


def is_replay_safe_external_outcome(value: object) -> bool:
    return str(value or "unknown") in REPLAY_SAFE_EXTERNAL_OUTCOMES


@dataclass(frozen=True, slots=True)
class HarnessRunRecovery:
    """A durable harness run and its existing background-job ownership."""

    run_id: str
    thread_id: str
    job_id: str
    assistant_id: str | None = None
    user_id: str | None = None
    status: str = "pending"
    on_disconnect: str = "cancel"
    multitask_strategy: str = "reject"
    metadata: dict[str, Any] = field(default_factory=dict)
    kwargs: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    created_at: str = ""
    updated_at: str = ""
    attempt: int = 0
    job_status: str = "running"
    checkpoint_id: str | None = None
    claim_token: str | None = None
    claim_expires_at: datetime | None = None
    requires_reconciliation: bool = True
    external_outcome: str = "unknown"
    kind: str = HARNESS_RUN_RECOVERY_KIND

    def has_valid_lease(self, now: datetime) -> bool:
        if self.claim_token is None:
            return False
        if self.claim_expires_at is None:
            return False
        expires_at = self.claim_expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return expires_at > now


@dataclass(slots=True)
class RunHydrationResult:
    supported: bool
    hydrated: list[str] = field(default_factory=list)
    requeued: list[str] = field(default_factory=list)
    active: list[str] = field(default_factory=list)
    terminal: list[str] = field(default_factory=list)
    reconciliation_required: list[str] = field(default_factory=list)


class RunRecoveryMixin:
    """Hydrate the single durable harness-run profile without executing jobs locally."""

    def _start_run_heartbeat(self, record: Any) -> None:
        if not record.inflight or record.heartbeat_task is not None:
            return
        heartbeat = getattr(self._store, "heartbeat_harness_run", None)
        if not callable(heartbeat):
            return
        running_loop = asyncio.get_running_loop()
        if self._loop is None or not self._loop.is_running():
            self._loop = running_loop
        record.heartbeat_task = running_loop.create_task(
            self._heartbeat_run(record, heartbeat),
            name=f"harness-run-heartbeat-{record.run_id}",
        )

    async def _heartbeat_run(
        self,
        record: Any,
        heartbeat: Callable[..., Awaitable[bool]],
    ) -> None:
        while record.inflight:
            try:
                alive = await heartbeat(
                    record.run_id,
                    ttl_seconds=self._heartbeat_ttl_seconds,
                )
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Failed to heartbeat API harness run %s; retrying",
                    record.run_id,
                    exc_info=True,
                )
            else:
                if not alive:
                    await self._require_reconciliation(
                        record,
                        error="API harness run lease heartbeat lost",
                    )
                    return
            await asyncio.sleep(self._heartbeat_interval_seconds)

    def _cancel_run_heartbeat(self, record: Any) -> asyncio.Task[None] | None:
        task = record.heartbeat_task
        record.heartbeat_task = None
        if task is None or task.done() or task is asyncio.current_task():
            return None
        task.cancel()
        return task

    async def _await_run_heartbeat(self, task: asyncio.Task[None] | None) -> None:
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    async def _stop_run_heartbeat(self, record: Any) -> None:
        await self._await_run_heartbeat(self._cancel_run_heartbeat(record))

    async def hydrate(self) -> RunHydrationResult:
        from .runs import RunStatus, is_execution_terminal_run_status

        store = self._store
        list_recoveries = getattr(store, "list_harness_run_recoveries", None)
        requeue = getattr(store, "requeue_harness_run", None)
        if not callable(list_recoveries) or not callable(requeue):
            return RunHydrationResult(supported=False)

        result = RunHydrationResult(supported=True)
        recoveries = await list_recoveries(kind=HARNESS_RUN_RECOVERY_KIND)
        now = datetime.now(UTC)
        for recovery in recoveries:
            if recovery.kind != HARNESS_RUN_RECOVERY_KIND:
                continue
            if is_execution_terminal_run_status(recovery.status):
                result.terminal.append(recovery.run_id)
                continue

            async with self._lock:
                if recovery.run_id in self._runs:
                    continue
            record = self._recovery_record(recovery)
            async with self._lock:
                self._runs[recovery.run_id] = record
            result.hydrated.append(recovery.run_id)

            if record.status == RunStatus.RECONCILIATION_REQUIRED:
                if recovery.status != "reconciliation_required":
                    await self._require_reconciliation(record)
                result.reconciliation_required.append(record.run_id)
                continue
            if record.task is not None and not record.task.done():
                result.active.append(record.run_id)
                continue
            if recovery.job_status in {"pending", "retrying"} or recovery.has_valid_lease(now):
                result.active.append(record.run_id)
                continue

            try:
                requeued = await requeue(
                    run_id=record.run_id,
                    job_id=recovery.job_id,
                    claim_token=recovery.claim_token,
                )
            except Exception as exc:
                await self._require_reconciliation(record, error=str(exc))
                result.reconciliation_required.append(record.run_id)
                continue
            if requeued is True:
                result.requeued.append(record.run_id)
            elif requeued is False:
                result.active.append(record.run_id)
            else:
                await self._require_reconciliation(
                    record,
                    error="Durable harness job state could not be reconciled",
                )
                result.reconciliation_required.append(record.run_id)
        return result

    def _recovery_record(self, recovery: HarnessRunRecovery):
        from .rollback import ROLLBACK_TARGET_METADATA_KEY, CheckpointRollbackTarget
        from .runs import DisconnectMode, MultitaskStrategy, RunRecord, RunStatus

        kwargs = dict(recovery.kwargs)
        checkpoint_id = recovery.checkpoint_id or kwargs.get("checkpoint_id")
        if checkpoint_id is not None:
            kwargs["checkpoint_id"] = checkpoint_id
        metadata = dict(recovery.metadata)
        raw_rollback_target = metadata.get(ROLLBACK_TARGET_METADATA_KEY)
        rollback_target = None
        if isinstance(raw_rollback_target, dict) and raw_rollback_target.get("thread_id"):
            rollback_target = CheckpointRollbackTarget(
                thread_id=str(raw_rollback_target["thread_id"]),
                checkpoint_ns=str(raw_rollback_target.get("checkpoint_ns") or ""),
                checkpoint_id=raw_rollback_target.get("checkpoint_id"),
                metadata={},
            )
        metadata["external_outcome"] = recovery.external_outcome
        status = (
            RunStatus.RECONCILIATION_REQUIRED
            if self._needs_reconciliation(recovery)
            else RunStatus(recovery.status)
        )
        return RunRecord(
            run_id=recovery.run_id,
            thread_id=recovery.thread_id,
            assistant_id=recovery.assistant_id,
            status=status,
            on_disconnect=DisconnectMode(recovery.on_disconnect),
            multitask_strategy=MultitaskStrategy(recovery.multitask_strategy),
            metadata=metadata,
            kwargs=kwargs,
            user_id=recovery.user_id,
            rollback_target=rollback_target,
            created_at=recovery.created_at,
            updated_at=recovery.updated_at,
            error=recovery.error,
        )

    @staticmethod
    def _needs_reconciliation(recovery: HarnessRunRecovery) -> bool:
        persisted_checkpoint = recovery.kwargs.get("checkpoint_id")
        checkpoint_mismatch = (
            recovery.checkpoint_id is not None
            and persisted_checkpoint is not None
            and recovery.checkpoint_id != persisted_checkpoint
        )
        if (
            recovery.requires_reconciliation
            or recovery.status == "reconciliation_required"
            or checkpoint_mismatch
            or (
                recovery.job_status == "running"
                and (recovery.claim_token is None or recovery.claim_expires_at is None)
            )
        ):
            return True
        if recovery.job_status == "running" and recovery.has_valid_lease(datetime.now(UTC)):
            return False
        return recovery.status == "running" and not is_replay_safe_external_outcome(
            recovery.external_outcome
        )

    async def _require_reconciliation(self, record, error: str | None = None) -> None:
        from .runs import RunStatus

        await self.set_status(
            record.run_id,
            RunStatus.RECONCILIATION_REQUIRED,
            error=error,
        )


__all__ = [
    "HARNESS_RUN_API_CLAIM_OWNER",
    "HARNESS_RUN_API_LEASE_TTL_SECONDS",
    "HARNESS_RUN_RECOVERY_KIND",
    "HarnessRunRecovery",
    "REPLAY_SAFE_EXTERNAL_OUTCOMES",
    "RunHydrationResult",
    "is_replay_safe_external_outcome",
]
