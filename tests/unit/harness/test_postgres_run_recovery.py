import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from focus_agent.harness.observability.postgres_run_journal import PostgresRunJournal
from focus_agent.services.coordination_postgres import PostgresBackgroundJobDeduperBackend


class _Cursor:
    def __init__(self, results):
        self.results = list(results)
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def execute(self, sql, params=None):
        self.statements.append((sql, params))

    def fetchall(self):
        return self.results.pop(0)

    def fetchone(self):
        return self.results.pop(0)


class _Connection:
    def __init__(self, results):
        self.cursor_instance = _Cursor(results)

    def cursor(self):
        return self.cursor_instance

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None


class _Journal(PostgresRunJournal):
    def __init__(self, results):
        self.connection = _Connection(results)

    async def _run_db(self, operation):
        return operation(self.connection)


def _run_row(**overrides):
    row = {
        "run_id": "run-1",
        "thread_id": "thread-1",
        "assistant_id": "focus-agent",
        "user_id": "user-1",
        "status": "running",
        "on_disconnect": "continue",
        "multitask_strategy": "reject",
        "metadata_json": {},
        "kwargs_json": {"checkpoint_id": "checkpoint-1", "input": {"value": 1}},
        "error": None,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
        "completion_json": {},
        "recovery_job_key": "harness_run:run-1",
        "recovery_job_status": "running",
        "recovery_attempt": 2,
        "recovery_claim_token": "claim-2",
        "recovery_claimed_until": datetime.now(UTC) + timedelta(minutes=5),
        "recovery_idempotency_key": "harness_run:run-1",
        "recovery_payload": {
            "run_id": "run-1",
            "checkpoint_id": "checkpoint-1",
            "external_outcome": "replay_safe",
        },
    }
    row.update(overrides)
    return row


def test_postgres_recovery_hydrates_original_run_job_attempt_and_checkpoint():
    async def scenario():
        journal = _Journal([[_run_row()]])

        recoveries = await journal.list_harness_run_recoveries()

        assert len(recoveries) == 1
        recovery = recoveries[0]
        assert recovery.run_id == "run-1"
        assert recovery.job_id == "harness_run:run-1"
        assert recovery.job_status == "running"
        assert recovery.attempt == 2
        assert recovery.checkpoint_id == "checkpoint-1"
        assert recovery.kwargs["input"] == {"value": 1}
        assert recovery.claim_token == "claim-2"
        assert not recovery.requires_reconciliation
        sql, params = journal.connection.cursor_instance.statements[0]
        assert "JOIN focus_background_jobs AS jobs" in sql
        assert "jobs.payload->>'run_id' = runs.run_id" in sql
        assert params == ("harness_run",)

    asyncio.run(scenario())


def test_postgres_recovery_preserves_policy_evidence_without_duplicating_policy():
    async def scenario():
        payload = {
            "run_id": "run-1",
            "checkpoint_id": "checkpoint-other",
            "external_outcome": "unknown",
        }
        journal = _Journal([[_run_row(recovery_payload=payload)]])

        recovery = (await journal.list_harness_run_recoveries())[0]

        assert not recovery.requires_reconciliation
        assert recovery.external_outcome == "unknown"
        assert recovery.checkpoint_id == "checkpoint-other"

    asyncio.run(scenario())


def test_postgres_pending_run_can_recover_with_unknown_external_outcome():
    async def scenario():
        journal = _Journal(
            [
                [
                    _run_row(
                        status="pending",
                        recovery_payload={
                            "run_id": "run-1",
                            "checkpoint_id": "checkpoint-1",
                            "external_outcome": "unknown",
                        },
                    )
                ]
            ]
        )

        recovery = (await journal.list_harness_run_recoveries())[0]

        assert not recovery.requires_reconciliation
        assert recovery.external_outcome == "unknown"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("results", "expected"),
    [
        ([{"job_key": "harness_run:run-1"}], True),
        ([None, {"active": True}], False),
        ([None, None], None),
    ],
)
def test_postgres_requeue_is_claim_fenced_and_distinguishes_unknown_state(
    results,
    expected,
):
    async def scenario():
        journal = _Journal(results)

        result = await journal.requeue_harness_run(
            run_id="run-1",
            job_id="harness_run:run-1",
            claim_token="claim-1",
        )

        assert result is expected
        update_sql, update_params = journal.connection.cursor_instance.statements[0]
        assert "UPDATE focus_background_jobs" in update_sql
        assert "status = 'running'" in update_sql
        assert "claim_token = %s" in update_sql
        assert "claimed_until <= now()" in update_sql
        assert "attempt < max_attempts" in update_sql
        assert "idempotency_key = job_key" in update_sql
        assert "payload->>'external_outcome' = ANY(%s)" in update_sql
        assert "runs.status = 'pending'" in update_sql
        assert update_params == (
            "harness_run:run-1",
            "harness_run",
            "run-1",
            ["reconciled", "replay_safe"],
            "claim-1",
        )

    asyncio.run(scenario())


def test_postgres_api_heartbeat_is_lease_owner_and_run_status_fenced():
    async def scenario():
        journal = _Journal([{"job_key": "harness_run:run-1"}])

        alive = await journal.heartbeat_harness_run("run-1", ttl_seconds=30.0)

        assert alive is True
        sql, params = journal.connection.cursor_instance.statements[0]
        assert "jobs.claimed_by = %s" in sql
        assert "jobs.claimed_until > now()" in sql
        assert "runs.status IN ('pending', 'running')" in sql
        assert params[1:] == ("harness_run:run-1", "harness_run", "api", "run-1")

    asyncio.run(scenario())


def test_postgres_execution_terminal_status_finalizes_only_api_lease():
    async def scenario():
        journal = _Journal([])

        await journal.update_status("run-1", "success")

        statements = journal.connection.cursor_instance.statements
        assert len(statements) == 2
        sql, params = statements[1]
        assert "status = 'succeeded'" in sql
        assert "claimed_by = %s" in sql
        assert "claimed_until = NULL" in sql
        assert "claim_token = NULL" in sql
        assert params == ("harness_run:run-1", "harness_run", "api")

        reconciliation = _Journal([])
        await reconciliation.update_status("run-1", "reconciliation_required")
        assert len(reconciliation.connection.cursor_instance.statements) == 1

    asyncio.run(scenario())


def test_generic_expiry_applies_harness_replay_safety_gate():
    connection = _Connection([None])

    class Provider:
        def connect(self, *, row_factory=None):
            return connection

    backend = PostgresBackgroundJobDeduperBackend(
        "postgresql://test",
        connection_provider=Provider(),
    )

    assert backend.claim_next_job(allowed_kinds=("harness_run",)) is None
    expiry_sql, expiry_params = connection.cursor_instance.statements[0]
    claim_sql, _ = connection.cursor_instance.statements[1]
    assert "kind <> 'harness_run'" in expiry_sql
    assert "runs.status = 'pending'" in expiry_sql
    assert "runs.status = 'running'" in expiry_sql
    assert "payload->>'external_outcome' = ANY(%s)" in expiry_sql
    assert expiry_params[-1] == ["reconciled", "replay_safe"]
    assert "AND kind <> 'harness_run'" in claim_sql
