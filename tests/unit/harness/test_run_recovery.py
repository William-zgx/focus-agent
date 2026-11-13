import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from focus_agent.harness.runtime import (
    HarnessRunRecovery,
    RunManager,
    RunStatus,
)
from focus_agent.harness.runtime.rollback import ROLLBACK_TARGET_METADATA_KEY
from focus_agent.harness.runtime.runs import (
    EXECUTION_TERMINAL_RUN_STATUSES,
    REPLAYABLE_RUN_STATUSES,
    STREAM_TERMINAL_RUN_STATUSES,
    is_execution_terminal_run_status,
    is_replay_safe_run_status,
    is_stream_terminal_run_status,
)


class _RecoveryStore:
    def __init__(
        self,
        recoveries,
        *,
        heartbeat_interval_seconds=60.0,
        heartbeat_ttl_seconds=300.0,
    ):
        self.recoveries = list(recoveries)
        self.harness_run_heartbeat_interval_seconds = heartbeat_interval_seconds
        self.harness_run_lease_ttl_seconds = heartbeat_ttl_seconds
        self.requeues = []
        self.statuses = []
        self.puts = []
        self.heartbeats = []

    async def put(self, run_id, **kwargs):
        self.puts.append((run_id, kwargs))
        now = datetime.now(UTC)
        metadata = dict(kwargs.get("metadata") or {})
        run_kwargs = dict(kwargs.get("kwargs") or {})
        self.recoveries.append(
            HarnessRunRecovery(
                run_id=run_id,
                thread_id=kwargs["thread_id"],
                job_id=f"harness_run:{run_id}",
                assistant_id=kwargs.get("assistant_id"),
                user_id=kwargs.get("user_id"),
                status=kwargs.get("status", "pending"),
                on_disconnect=kwargs.get("on_disconnect", "cancel"),
                multitask_strategy=kwargs.get("multitask_strategy", "reject"),
                metadata=metadata,
                kwargs=run_kwargs,
                error=kwargs.get("error"),
                created_at=kwargs.get("created_at") or now.isoformat(),
                updated_at=now.isoformat(),
                checkpoint_id=run_kwargs.get("checkpoint_id"),
                claim_token=f"claim-{run_id}",
                claim_expires_at=now + timedelta(minutes=5),
                requires_reconciliation=False,
                external_outcome=str(metadata.get("external_outcome") or "unknown"),
            )
        )

    async def heartbeat_harness_run(self, run_id, *, ttl_seconds):
        now = datetime.now(UTC)
        self.heartbeats.append((run_id, ttl_seconds))
        for index, recovery in enumerate(self.recoveries):
            if (
                recovery.run_id != run_id
                or recovery.status not in {"pending", "running"}
                or recovery.job_status != "running"
                or not recovery.has_valid_lease(now)
            ):
                continue
            self.recoveries[index] = replace(
                recovery,
                claim_expires_at=now + timedelta(seconds=ttl_seconds),
            )
            return True
        return False

    async def update_status(self, run_id, status, *, error=None):
        self.statuses.append((run_id, status, error))
        execution_terminal = is_execution_terminal_run_status(status)
        self.recoveries = [
            replace(
                recovery,
                status=status,
                error=error if error is not None else recovery.error,
                job_status="succeeded" if execution_terminal else recovery.job_status,
                claim_token=None if execution_terminal else recovery.claim_token,
                claim_expires_at=None if execution_terminal else recovery.claim_expires_at,
            )
            if recovery.run_id == run_id
            else recovery
            for recovery in self.recoveries
        ]

    async def update_run_completion(self, run_id, **kwargs):
        return None

    async def list_harness_run_recoveries(self, *, kind):
        assert kind == "harness_run"
        return list(self.recoveries)

    async def requeue_harness_run(self, *, run_id, job_id, claim_token):
        now = datetime.now(UTC)
        for index, recovery in enumerate(self.recoveries):
            if (
                recovery.run_id != run_id
                or recovery.job_id != job_id
                or recovery.claim_token != claim_token
                or recovery.has_valid_lease(now)
            ):
                continue
            self.requeues.append(
                {
                    "run_id": run_id,
                    "job_id": job_id,
                    "claim_token": claim_token,
                }
            )
            self.recoveries[index] = replace(
                recovery,
                attempt=recovery.attempt + 1,
                claim_token=f"claim-{recovery.attempt + 1}",
                claim_expires_at=now + timedelta(minutes=5),
            )
            return True
        return False


def _recovery(**overrides):
    values = {
        "run_id": "run-1",
        "thread_id": "thread-1",
        "job_id": "harness_run:run-1",
        "assistant_id": "focus-agent",
        "user_id": "user-1",
        "status": "running",
        "metadata": {"source": "test"},
        "kwargs": {
            "input": {"messages": ["hello"]},
            "checkpoint_id": "checkpoint-1",
            "config": {"configurable": {"thread_id": "thread-1"}},
        },
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:01+00:00",
        "attempt": 1,
        "checkpoint_id": "checkpoint-1",
        "claim_token": "claim-1",
        "claim_expires_at": datetime.now(UTC) - timedelta(seconds=1),
        "requires_reconciliation": False,
    }
    values.update(overrides)
    return HarnessRunRecovery(**values)


def test_new_manager_hydrates_and_requeues_expired_lease_with_stable_identity():
    async def scenario():
        store = _RecoveryStore([_recovery(status="pending")])
        manager = RunManager(store=store)

        result = await manager.hydrate()

        record = manager.get("run-1")
        assert result.supported
        assert result.hydrated == ["run-1"]
        assert result.requeued == ["run-1"]
        assert store.requeues == [
            {
                "run_id": "run-1",
                "job_id": "harness_run:run-1",
                "claim_token": "claim-1",
            }
        ]
        assert "attempt" not in store.requeues[0]
        assert record is not None
        assert record.run_id == "run-1"
        assert record.thread_id == "thread-1"
        assert record.user_id == "user-1"
        assert record.kwargs == _recovery().kwargs
        assert record.kwargs["checkpoint_id"] == "checkpoint-1"
        assert record.created_at == "2026-01-01T00:00:00+00:00"
        assert record.task is None
        assert store.puts == []

    asyncio.run(scenario())


def test_hydration_restores_checkpoint_rollback_target():
    async def scenario():
        store = _RecoveryStore(
            [
                _recovery(
                    status="pending",
                    metadata={
                        ROLLBACK_TARGET_METADATA_KEY: {
                            "thread_id": "thread-1",
                            "checkpoint_ns": "branch-ns",
                            "checkpoint_id": "checkpoint-before-run",
                        }
                    },
                )
            ]
        )
        manager = RunManager(store=store)

        await manager.hydrate()

        target = manager.get("run-1").rollback_target
        assert target is not None
        assert target.thread_id == "thread-1"
        assert target.checkpoint_ns == "branch-ns"
        assert target.checkpoint_id == "checkpoint-before-run"

    asyncio.run(scenario())


def test_hydration_skips_terminal_run():
    async def scenario():
        store = _RecoveryStore([_recovery(status="success")])
        manager = RunManager(store=store)

        result = await manager.hydrate()

        assert result.terminal == ["run-1"]
        assert result.hydrated == []
        assert manager.get("run-1") is None
        assert store.requeues == []

    asyncio.run(scenario())


def test_hydration_does_not_requeue_valid_lease_or_create_task():
    async def scenario():
        store = _RecoveryStore(
            [
                _recovery(
                    claim_expires_at=datetime.now(UTC) + timedelta(minutes=5),
                    external_outcome="unknown",
                )
            ]
        )
        manager = RunManager(store=store)

        result = await manager.hydrate()

        assert result.active == ["run-1"]
        assert result.requeued == []
        assert store.requeues == []
        assert manager.get("run-1").status is RunStatus.RUNNING
        assert manager.get("run-1").task is None
        assert store.statuses == []

    asyncio.run(scenario())


def test_repeated_hydration_and_second_manager_do_not_requeue_twice():
    async def scenario():
        store = _RecoveryStore([_recovery(external_outcome="replay_safe")])
        first_manager = RunManager(store=store)

        first = await first_manager.hydrate()
        repeated = await first_manager.hydrate()
        second_manager = RunManager(store=store)
        second = await second_manager.hydrate()

        assert first.requeued == ["run-1"]
        assert repeated.hydrated == []
        assert repeated.requeued == []
        assert second.hydrated == ["run-1"]
        assert second.active == ["run-1"]
        assert second.requeued == []
        assert len(store.requeues) == 1
        assert store.recoveries[0].attempt == 2
        assert store.recoveries[0].job_id == "harness_run:run-1"
        assert second_manager.get("run-1").task is None

    asyncio.run(scenario())


def test_hydration_preserves_active_task_without_creating_another():
    async def scenario():
        recovery = _recovery()
        store = _RecoveryStore([recovery])
        manager = RunManager(store=store)
        record = await manager.create(
            recovery.thread_id,
            recovery.assistant_id,
            kwargs=recovery.kwargs,
        )
        store.recoveries = [replace(recovery, run_id=record.run_id, job_id=record.run_id)]
        started = asyncio.Event()

        async def execute():
            started.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(execute())
        await started.wait()
        await manager.attach_task(record.run_id, task)

        result = await manager.hydrate()

        assert result.hydrated == []
        assert result.requeued == []
        assert store.requeues == []
        assert manager.get(record.run_id) is record
        assert record.task is task
        assert len(await manager.list_by_thread(record.thread_id)) == 1
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())


def test_unknown_external_outcome_requires_reconciliation_without_retry():
    async def scenario():
        store = _RecoveryStore([_recovery()])
        manager = RunManager(store=store)

        result = await manager.hydrate()
        repeated = await manager.hydrate()

        record = manager.get("run-1")
        assert result.reconciliation_required == ["run-1"]
        assert result.requeued == []
        assert repeated.reconciliation_required == []
        assert record.status is RunStatus.RECONCILIATION_REQUIRED
        assert not record.inflight
        assert store.requeues == []
        assert store.statuses == [("run-1", "reconciliation_required", None)]

    asyncio.run(scenario())


def test_reconciled_run_can_transition_back_to_pending():
    async def scenario():
        manager = RunManager()
        record = await manager.create("thread-1", user_id="user-1", kwargs={"input": {}})
        await manager.set_status(record.run_id, RunStatus.RECONCILIATION_REQUIRED)
        record.metadata["external_outcome"] = "reconciled"

        await manager.set_status(record.run_id, RunStatus.PENDING)

        assert manager.get(record.run_id).status is RunStatus.PENDING
        assert manager.get(record.run_id).error is None

    asyncio.run(scenario())


def test_unreconciled_terminal_run_cannot_transition_back_to_pending():
    async def scenario():
        manager = RunManager()
        record = await manager.create("thread-1", user_id="user-1", kwargs={"input": {}})
        await manager.set_status(record.run_id, RunStatus.RECONCILIATION_REQUIRED)
        record.metadata["external_outcome"] = "unknown"

        await manager.set_status(record.run_id, RunStatus.PENDING)

        assert manager.get(record.run_id).status is RunStatus.RECONCILIATION_REQUIRED

    asyncio.run(scenario())


def test_running_job_without_complete_lease_requires_reconciliation():
    async def scenario():
        store = _RecoveryStore(
            [
                _recovery(
                    external_outcome="replay_safe",
                    claim_token=None,
                    claim_expires_at=None,
                )
            ]
        )
        manager = RunManager(store=store)

        result = await manager.hydrate()

        assert result.reconciliation_required == ["run-1"]
        assert result.active == []
        assert store.requeues == []
        assert store.statuses == [("run-1", "reconciliation_required", None)]

    asyncio.run(scenario())


def test_queued_job_without_claim_is_active_not_reconciliation_required():
    async def scenario():
        store = _RecoveryStore(
            [
                _recovery(
                    status="pending",
                    job_status="retrying",
                    claim_token=None,
                    claim_expires_at=None,
                )
            ]
        )
        manager = RunManager(store=store)

        result = await manager.hydrate()

        assert result.active == ["run-1"]
        assert result.reconciliation_required == []
        assert store.requeues == []
        assert store.statuses == []

    asyncio.run(scenario())


def test_existing_reconciliation_status_is_not_redundantly_persisted():
    async def scenario():
        store = _RecoveryStore([_recovery(status="reconciliation_required")])
        manager = RunManager(store=store)

        result = await manager.hydrate()

        assert result.reconciliation_required == ["run-1"]
        assert manager.get("run-1").status is RunStatus.RECONCILIATION_REQUIRED
        assert store.statuses == []

    asyncio.run(scenario())


def test_unknown_requeue_result_requires_reconciliation_without_retry():
    async def scenario():
        store = _RecoveryStore([_recovery(external_outcome="replay_safe")])

        async def unknown_requeue(**kwargs):
            return None

        store.requeue_harness_run = unknown_requeue
        manager = RunManager(store=store)

        result = await manager.hydrate()

        assert result.reconciliation_required == ["run-1"]
        assert result.active == []
        assert result.requeued == []
        assert manager.get("run-1").status is RunStatus.RECONCILIATION_REQUIRED
        assert store.statuses == [
            (
                "run-1",
                "reconciliation_required",
                "Durable harness job state could not be reconciled",
            )
        ]

    asyncio.run(scenario())


def test_checkpoint_mismatch_requires_reconciliation_without_retry():
    async def scenario():
        store = _RecoveryStore(
            [
                _recovery(
                    checkpoint_id="checkpoint-new",
                    kwargs={"input": {"messages": ["hello"]}, "checkpoint_id": "checkpoint-old"},
                )
            ]
        )
        manager = RunManager(store=store)

        result = await manager.hydrate()

        assert result.reconciliation_required == ["run-1"]
        assert manager.get("run-1").status is RunStatus.RECONCILIATION_REQUIRED
        assert store.requeues == []

    asyncio.run(scenario())


def test_legacy_store_recovery_is_explicitly_unsupported():
    class LegacyStore:
        async def put(self, run_id, **kwargs):
            return None

        async def update_status(self, run_id, status, *, error=None):
            return None

        async def update_run_completion(self, run_id, **kwargs):
            return None

    async def scenario():
        manager = RunManager(store=LegacyStore())

        result = await manager.hydrate()

        assert not result.supported
        assert result.hydrated == []
        assert result.requeued == []

    asyncio.run(scenario())


def test_run_status_terminal_and_replay_table():
    rows = [
        (RunStatus.PENDING, False, False, True),
        (RunStatus.RUNNING, False, False, True),
        (RunStatus.SUCCESS, True, True, False),
        (RunStatus.ERROR, True, True, False),
        (RunStatus.TIMEOUT, True, True, False),
        (RunStatus.INTERRUPTED, True, True, False),
        (RunStatus.RECONCILIATION_REQUIRED, False, True, False),
    ]

    for status, execution_terminal, stream_terminal, replay_safe in rows:
        assert (status in EXECUTION_TERMINAL_RUN_STATUSES) is execution_terminal
        assert (status in STREAM_TERMINAL_RUN_STATUSES) is stream_terminal
        assert (status in REPLAYABLE_RUN_STATUSES) is replay_safe
        assert is_execution_terminal_run_status(status) is execution_terminal
        assert is_execution_terminal_run_status(status.value) is execution_terminal
        assert is_stream_terminal_run_status(status) is stream_terminal
        assert is_stream_terminal_run_status(status.value) is stream_terminal
        assert is_replay_safe_run_status(status) is replay_safe
        assert is_replay_safe_run_status(status.value) is replay_safe


def test_api_heartbeat_keeps_long_lived_pending_run_active():
    async def scenario():
        store = _RecoveryStore(
            [],
            heartbeat_interval_seconds=0.01,
            heartbeat_ttl_seconds=0.03,
        )
        manager = RunManager(store=store)
        record = await manager.create(
            "thread-long-lived",
            metadata={"external_outcome": "replay_safe"},
        )

        await asyncio.sleep(0.075)
        replica = RunManager(store=store)
        result = await replica.hydrate()

        assert result.active == [record.run_id]
        assert result.requeued == []
        assert store.requeues == []
        assert len(store.heartbeats) >= 3
        assert replica.get(record.run_id).heartbeat_task is None
        await manager.close()

    asyncio.run(scenario())


def test_api_lease_expires_after_manager_stops_and_recovers_once():
    async def scenario():
        store = _RecoveryStore(
            [],
            heartbeat_interval_seconds=0.01,
            heartbeat_ttl_seconds=0.03,
        )
        manager = RunManager(store=store)
        record = await manager.create(
            "thread-stopped",
            metadata={"external_outcome": "replay_safe"},
        )
        await asyncio.sleep(0.02)
        await manager.close()
        heartbeat_count = len(store.heartbeats)

        await asyncio.sleep(0.05)
        assert len(store.heartbeats) == heartbeat_count
        recovered = await RunManager(store=store).hydrate()

        assert recovered.requeued == [record.run_id]
        assert len(store.requeues) == 1

    asyncio.run(scenario())


def test_concurrent_replicas_do_not_requeue_the_same_expired_run_twice():
    async def scenario():
        store = _RecoveryStore([_recovery(external_outcome="replay_safe")])
        first_manager = RunManager(store=store)
        second_manager = RunManager(store=store)

        first, second = await asyncio.gather(
            first_manager.hydrate(),
            second_manager.hydrate(),
        )

        assert len(store.requeues) == 1
        assert [result.requeued for result in (first, second)].count(["run-1"]) == 1
        assert [result.active for result in (first, second)].count(["run-1"]) == 1

    asyncio.run(scenario())


def test_terminal_cross_loop_status_update_stops_heartbeat_and_finalizes_lease():
    async def scenario():
        store = _RecoveryStore(
            [],
            heartbeat_interval_seconds=0.01,
            heartbeat_ttl_seconds=0.03,
        )
        manager = RunManager(store=store)
        record = await manager.create("thread-terminal")
        heartbeat_task = record.heartbeat_task

        def update_from_another_loop():
            asyncio.run(manager.set_status(record.run_id, RunStatus.SUCCESS))

        await asyncio.to_thread(update_from_another_loop)
        heartbeat_count = len(store.heartbeats)
        await asyncio.sleep(0.04)

        assert heartbeat_task is not None and heartbeat_task.done()
        assert record.heartbeat_task is None
        assert len(store.heartbeats) == heartbeat_count
        assert store.recoveries[0].job_status == "succeeded"
        assert store.recoveries[0].claim_token is None
        result = await RunManager(store=store).hydrate()
        assert result.terminal == [record.run_id]
        assert result.requeued == []

    asyncio.run(scenario())
