from __future__ import annotations

import time

from focus_agent.services.coordination import (
    BackgroundJobClaim,
    BackgroundJobSpec,
    InMemoryAgentMessageBus,
    InMemoryApprovalQueue,
    InMemoryBackgroundJobDeduperBackend,
    InMemoryResourceLockManager,
    InMemoryThreadTurnLockBackend,
    PostgresAgentMessageBus,
    PostgresApprovalQueue,
    PostgresBackgroundJobDeduperBackend,
    PostgresRateLimitBackend,
    PostgresResourceLockManager,
    PostgresThreadTurnLockBackend,
    create_coordination_backend,
    create_in_memory_coordination_backend,
)


def test_in_memory_thread_turn_lock_respects_owner_and_ttl() -> None:
    backend = InMemoryThreadTurnLockBackend()

    assert backend.acquire_thread_turn(thread_id="thread-1", owner="owner-a", ttl_seconds=0.01)
    assert not backend.acquire_thread_turn(thread_id="thread-1", owner="owner-b", ttl_seconds=1.0)
    assert backend.heartbeat_thread_turn(thread_id="thread-1", owner="owner-a", ttl_seconds=1.0)
    backend.release_thread_turn(thread_id="thread-1", owner="owner-b")
    assert not backend.acquire_thread_turn(thread_id="thread-1", owner="owner-b", ttl_seconds=1.0)
    backend.release_thread_turn(thread_id="thread-1", owner="owner-a")
    assert backend.acquire_thread_turn(thread_id="thread-1", owner="owner-b", ttl_seconds=1.0)

    assert backend.acquire_thread_turn(
        thread_id="thread-expiring", owner="owner-a", ttl_seconds=0.001
    )
    time.sleep(0.01)
    assert backend.acquire_thread_turn(
        thread_id="thread-expiring", owner="owner-b", ttl_seconds=1.0
    )


def test_coordination_backend_includes_in_memory_multi_agent_ports() -> None:
    backend = create_in_memory_coordination_backend()

    assert isinstance(backend.resource_locks, InMemoryResourceLockManager)
    assert isinstance(backend.message_bus, InMemoryAgentMessageBus)
    assert isinstance(backend.approval_queue, InMemoryApprovalQueue)


def test_coordination_backend_uses_postgres_multi_agent_ports_when_enabled() -> None:
    backend = create_coordination_backend(
        database_uri="postgresql://example/db",
        multi_agent_enabled=True,
        multi_agent_message_ttl_seconds=123,
    )

    assert isinstance(backend.thread_turns, PostgresThreadTurnLockBackend)
    assert isinstance(backend.resource_locks, PostgresResourceLockManager)
    assert isinstance(backend.message_bus, PostgresAgentMessageBus)
    assert isinstance(backend.rate_limiter, PostgresRateLimitBackend)
    assert isinstance(backend.approval_queue, PostgresApprovalQueue)
    assert backend.message_bus.default_ttl_seconds == 123


def test_postgres_rate_limit_backend_uses_shared_bucket_table(monkeypatch) -> None:
    executed: list[tuple[str, object]] = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            executed.append((sql, params))

        def fetchone(self):
            return {"token_count": 2, "retry_after_seconds": 12.5}

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(
        "focus_agent.services.coordination.psycopg.connect",
        lambda uri, row_factory=None: FakeConnection(),
    )

    backend = PostgresRateLimitBackend("postgresql://example")
    result = backend.check(key="principal:user-1", limit=2, window_seconds=60.0)

    statement = " ".join(executed[0][0].split())
    assert "INSERT INTO focus_rate_limit_buckets" in statement
    assert "ON CONFLICT (bucket_key) DO UPDATE" in statement
    assert "token_count = CASE" in statement
    assert "focus_rate_limit_buckets.token_count < %s" in statement
    assert executed[0][1] == ("principal:user-1", 60.0, 2, 60.0, 60.0)
    assert result.allowed is True
    assert result.remaining == 0


def test_postgres_rate_limit_backend_rejects_when_bucket_is_full(monkeypatch) -> None:
    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            self.sql = sql
            self.params = params

        def fetchone(self):
            return {"token_count": 3, "retry_after_seconds": 7.25}

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(
        "focus_agent.services.coordination.psycopg.connect",
        lambda uri, row_factory=None: FakeConnection(),
    )

    result = PostgresRateLimitBackend("postgresql://example").check(
        key="principal:user-1",
        limit=2,
        window_seconds=60.0,
    )

    assert result.allowed is False
    assert result.remaining == 0
    assert result.retry_after_seconds == 7.25


def test_in_memory_background_job_heartbeats_and_rejects_stale_claims() -> None:
    backend = InMemoryBackgroundJobDeduperBackend(retry_base_delay_seconds=0.0)
    spec = BackgroundJobSpec(
        kind="conversation_title",
        key="chat:conversation_title:thread-1",
        payload={"root_thread_id": "thread-1", "user_id": "user-1"},
        max_attempts=2,
    )

    assert backend.enqueue_job(spec)
    claimed = backend.claim_next_job(allowed_kinds=("conversation_title",), claim_ttl_seconds=1.0)
    assert claimed is not None
    _, claim = claimed
    backend.mark_job_claim_running(spec.key, claim)

    stale_claim = BackgroundJobClaim(
        claim_token="stale-token", owner=claim.owner, attempt=claim.attempt
    )
    assert not backend.heartbeat_job_claim(spec.key, stale_claim, ttl_seconds=1.0)
    backend.mark_job_claim_succeeded(spec.key, stale_claim)
    assert backend.snapshot()["job_running_total"] == 1

    assert backend.heartbeat_job_claim(spec.key, claim, ttl_seconds=0.001)
    time.sleep(0.01)
    assert not backend.heartbeat_job_claim(spec.key, claim, ttl_seconds=1.0)
    backend.mark_job_claim_succeeded(spec.key, claim)
    assert backend.snapshot()["job_succeeded_total"] == 0

    reclaimed = backend.claim_next_job(allowed_kinds=("conversation_title",), claim_ttl_seconds=1.0)
    assert reclaimed is not None
    _, next_claim = reclaimed
    assert next_claim.claim_token != claim.claim_token
    assert next_claim.attempt == 2


def test_in_memory_background_job_does_not_duplicate_live_pending_claim() -> None:
    backend = InMemoryBackgroundJobDeduperBackend()
    spec = BackgroundJobSpec(
        kind="conversation_title",
        key="chat:conversation_title:thread-dup",
        payload={"root_thread_id": "thread-dup", "user_id": "user-1"},
        max_attempts=2,
    )

    assert backend.enqueue_job(spec)
    first_claimed = backend.claim_next_job(
        allowed_kinds=("conversation_title",), claim_ttl_seconds=1.0
    )

    assert first_claimed is not None
    assert (
        backend.claim_next_job(allowed_kinds=("conversation_title",), claim_ttl_seconds=1.0) is None
    )


def test_in_memory_background_job_retries_with_backoff_then_dead_letters() -> None:
    backend = InMemoryBackgroundJobDeduperBackend(retry_base_delay_seconds=0.0)
    spec = BackgroundJobSpec(
        kind="conversation_title",
        key="chat:conversation_title:thread-retry",
        payload={"root_thread_id": "thread-retry", "user_id": "user-1"},
        max_attempts=2,
    )

    assert backend.enqueue_job(spec)
    first_claimed = backend.claim_next_job(
        allowed_kinds=("conversation_title",), claim_ttl_seconds=1.0
    )
    assert first_claimed is not None
    _, first_claim = first_claimed
    backend.mark_job_claim_failed(spec.key, first_claim, "transient")

    snapshot = backend.snapshot()
    assert snapshot["job_retrying_total"] == 1
    assert snapshot["job_dead_lettered_total"] == 0
    assert snapshot["job_oldest_retry_seconds"] >= 0

    second_claimed = backend.claim_next_job(
        allowed_kinds=("conversation_title",), claim_ttl_seconds=1.0
    )
    assert second_claimed is not None
    _, second_claim = second_claimed
    assert second_claim.attempt == 2
    backend.mark_job_claim_failed(spec.key, second_claim, "permanent")

    snapshot = backend.snapshot()
    assert snapshot["job_retrying_total"] == 0
    assert snapshot["job_dead_lettered_total"] == 1
    assert snapshot["job_oldest_dead_lettered_seconds"] >= 0


def test_in_memory_background_dead_letter_jobs_can_be_listed_and_replayed() -> None:
    backend = InMemoryBackgroundJobDeduperBackend(retry_base_delay_seconds=0.0)
    spec = BackgroundJobSpec(
        kind="conversation_title",
        key="chat:conversation_title:thread-dead-letter",
        payload={"root_thread_id": "thread-dead-letter", "user_id": "user-1"},
        max_attempts=1,
    )

    assert backend.enqueue_job(spec)
    claimed = backend.claim_next_job(
        allowed_kinds=("conversation_title",),
        claim_ttl_seconds=1.0,
    )
    assert claimed is not None
    _, claim = claimed
    backend.mark_job_claim_failed(spec.key, claim, "permanent")

    dead_letters = backend.list_dead_letter_jobs()

    assert dead_letters["count"] == 1
    assert dead_letters["items"][0]["job_key"] == spec.key
    assert dead_letters["items"][0]["payload"]["root_thread_id"] == "thread-dead-letter"
    assert dead_letters["items"][0]["last_error"] == "permanent"
    assert backend.replay_dead_letter_job(spec.key) is True
    assert backend.replay_dead_letter_job(spec.key) is False
    snapshot = backend.snapshot()
    assert snapshot["job_pending_total"] == 1
    assert snapshot["job_dead_lettered_total"] == 0


def test_postgres_thread_turn_lock_uses_owner_ttl_heartbeat_and_release(monkeypatch) -> None:
    executed: list[tuple[str, object]] = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            executed.append((sql, params))

        def fetchone(self):
            return {"owner": "owner-a"}

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(
        "focus_agent.services.coordination.psycopg.connect",
        lambda uri, row_factory=None: FakeConnection(),
    )

    backend = PostgresThreadTurnLockBackend("postgresql://example")

    assert backend.acquire_thread_turn(thread_id="thread-1", owner="owner-a", ttl_seconds=30.0)
    assert backend.heartbeat_thread_turn(thread_id="thread-1", owner="owner-a", ttl_seconds=30.0)
    backend.release_thread_turn(thread_id="thread-1", owner="owner-a")

    statements = [" ".join(sql.split()) for sql, _ in executed]
    assert "INSERT INTO focus_runtime_locks" in statements[0]
    assert "ON CONFLICT (lock_key) DO UPDATE" in statements[0]
    assert "expires_at <= now()" in statements[0]
    assert "UPDATE focus_runtime_locks SET heartbeat_at = now(), expires_at = %s" in statements[1]
    assert "DELETE FROM focus_runtime_locks" in statements[2]
    assert executed[0][1][0] == "thread_turn:thread-1"
    assert executed[0][1][1] == "owner-a"
    assert executed[1][1][1:] == ("thread_turn:thread-1", "owner-a")
    assert executed[2][1] == ("thread_turn:thread-1", "owner-a")


def test_postgres_background_job_backend_claim_retry_release_and_metrics(monkeypatch) -> None:
    executed: list[tuple[str, object]] = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            executed.append((sql, params))
            self._sql = " ".join(sql.split())

        def fetchone(self):
            if "RETURNING attempt, claim_token" in self._sql:
                return {"attempt": 2, "claim_token": "claim-token-1"}
            if "RETURNING job_key" in self._sql:
                return {"job_key": "chat:context_compaction:thread-1"}
            return None

        def fetchall(self):
            return [
                {"status": "pending", "count": 1, "attempts": 2},
                {"status": "failed", "count": 1, "attempts": 3},
            ]

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(
        "focus_agent.services.coordination.psycopg.connect",
        lambda uri, row_factory=None: FakeConnection(),
    )

    backend = PostgresBackgroundJobDeduperBackend(
        "postgresql://example",
        claim_ttl_seconds=45.0,
        owner="worker-1",
    )

    claim = backend.claim_job_key("chat:context_compaction:thread-1")
    assert claim == BackgroundJobClaim(claim_token="claim-token-1", owner="worker-1", attempt=2)
    backend.mark_job_running("chat:context_compaction:thread-1")
    assert backend.heartbeat_job_claim("chat:context_compaction:thread-1", claim, ttl_seconds=30.0)
    backend.mark_job_failed("chat:context_compaction:thread-1", "busy")
    backend.release_job_claim("chat:context_compaction:thread-1", claim)
    snapshot = backend.snapshot()

    statements = [" ".join(sql.split()) for sql, _ in executed]
    assert "INSERT INTO focus_background_jobs" in statements[0]
    assert "attempt = focus_background_jobs.attempt + 1" in statements[0]
    assert "claim_token = EXCLUDED.claim_token" in statements[0]
    assert "status = 'running'" in statements[1]
    assert "claim_token = %s" in statements[1]
    assert "claimed_until > now()" in statements[1]
    assert "SET claimed_until = %s" in statements[2]
    assert "WHERE job_key = %s AND claimed_by = %s AND claim_token = %s" in statements[2]
    assert "claimed_until > now()" in statements[2]
    assert "WHEN attempt >= max_attempts THEN 'dead_lettered'" in statements[3]
    assert "ELSE 'retrying'" in statements[3]
    assert "make_interval" in statements[3]
    assert "claim_token = %s" in statements[3]
    assert "status = 'released'" in statements[4]
    assert "claim_token = %s" in statements[4]
    assert executed[0][1][0] == "chat:context_compaction:thread-1"
    assert executed[0][1][1] == "context_compaction"
    assert executed[0][1][2] == "worker-1"
    assert isinstance(executed[0][1][4], str)
    assert executed[2][1][1:] == ("chat:context_compaction:thread-1", "worker-1", "claim-token-1")
    assert executed[3][1][2:] == (
        "busy",
        "chat:context_compaction:thread-1",
        "worker-1",
        "claim-token-1",
    )
    assert snapshot["job_backend_durable"] == 1
    assert snapshot["job_pending_total"] == 1
    assert snapshot["job_failed_total"] == 1
    assert snapshot["job_dead_lettered_total"] == 0
    assert snapshot["job_attempt_total"] == 5


def test_postgres_background_job_heartbeat_guards_claim_and_extends_ttl(monkeypatch) -> None:
    executed: list[tuple[str, object]] = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            executed.append((sql, params))
            self._sql = " ".join(sql.split())

        def fetchone(self):
            if "RETURNING job_key" in self._sql:
                return {"job_key": "chat:branch_title:thread-1"}
            return None

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(
        "focus_agent.services.coordination.psycopg.connect",
        lambda uri, row_factory=None: FakeConnection(),
    )

    backend = PostgresBackgroundJobDeduperBackend(
        "postgresql://example",
        owner="worker-1",
    )
    claim = BackgroundJobClaim(claim_token="claim-token-1", owner="worker-1", attempt=1)

    assert backend.heartbeat_job_claim("chat:branch_title:thread-1", claim, ttl_seconds=30.0)

    statement = " ".join(executed[0][0].split())
    assert "UPDATE focus_background_jobs SET claimed_until = %s" in statement
    assert "last_heartbeat_at = now()" in statement
    assert "updated_at = now()" in statement
    assert "WHERE job_key = %s AND claimed_by = %s AND claim_token = %s" in statement
    assert "status = 'running'" in statement
    assert "claimed_until > now()" in statement
    assert executed[0][1][1:] == ("chat:branch_title:thread-1", "worker-1", "claim-token-1")


def test_postgres_background_job_success_requires_live_claim(monkeypatch) -> None:
    executed: list[tuple[str, object]] = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            executed.append((sql, params))

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(
        "focus_agent.services.coordination.psycopg.connect",
        lambda uri, row_factory=None: FakeConnection(),
    )

    backend = PostgresBackgroundJobDeduperBackend(
        "postgresql://example",
        owner="worker-old",
    )
    stale_claim = BackgroundJobClaim(claim_token="old-token", owner="worker-old", attempt=1)
    backend.mark_job_claim_succeeded("chat:branch_title:thread-1", stale_claim)

    statement = " ".join(executed[0][0].split())
    assert "claimed_by = %s" in statement
    assert "claim_token = %s" in statement
    assert "claimed_until > now()" in statement
    assert executed[0][1] == ("chat:branch_title:thread-1", "worker-old", "old-token")


def test_postgres_background_job_backend_enqueues_and_claims_specs(monkeypatch) -> None:
    executed: list[tuple[str, object]] = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            executed.append((sql, params))
            self._sql = " ".join(sql.split())

        def fetchone(self):
            if "RETURNING job_key" in self._sql:
                return {"job_key": "chat:conversation_title:thread-1"}
            if "RETURNING jobs.job_key" in self._sql:
                return {
                    "job_key": "chat:conversation_title:thread-1",
                    "kind": "conversation_title",
                    "payload": {"root_thread_id": "thread-1", "user_id": "user-1"},
                    "run_at": None,
                    "max_attempts": 3,
                    "dedupe_policy": "skip",
                    "attempt": 1,
                    "claim_token": "claim-token-2",
                }
            return None

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(
        "focus_agent.services.coordination.psycopg.connect",
        lambda uri, row_factory=None: FakeConnection(),
    )

    backend = PostgresBackgroundJobDeduperBackend(
        "postgresql://example",
        claim_ttl_seconds=45.0,
        owner="worker-1",
    )
    spec = BackgroundJobSpec(
        kind="conversation_title",
        key="chat:conversation_title:thread-1",
        payload={"root_thread_id": "thread-1", "user_id": "user-1"},
        max_attempts=3,
    )

    assert backend.enqueue_job(spec)
    claimed = backend.claim_next_job(allowed_kinds=("conversation_title",))

    assert claimed is not None
    claimed_spec, claim = claimed
    assert claimed_spec.kind == "conversation_title"
    assert claimed_spec.payload == {"root_thread_id": "thread-1", "user_id": "user-1"}
    assert claim == BackgroundJobClaim(claim_token="claim-token-2", owner="worker-1", attempt=1)

    statements = [" ".join(sql.split()) for sql, _ in executed]
    assert "kind" in statements[0]
    assert "payload" in statements[0]
    assert "run_at" in statements[0]
    assert "max_attempts" in statements[0]
    assert "dedupe_policy" in statements[0]
    assert "claim_token" in statements[0]
    assert "FOR UPDATE SKIP LOCKED" in statements[2]
    assert "kind = ANY(%s)" in statements[2]
    assert "status IN ('pending', 'retrying')" in statements[2]
    assert "claim_token IS NULL OR claimed_until IS NULL OR claimed_until <= now()" in statements[2]
    assert "SET status = 'running'" in statements[2]
    assert "claim_token = %s" in statements[2]
    assert executed[0][1][0] == "chat:conversation_title:thread-1"
    assert executed[0][1][1] == "conversation_title"
    assert executed[0][1][4] == 3
    assert executed[2][1][0] == ["conversation_title"]
    assert executed[2][1][1] == "worker-1"


def test_postgres_background_job_claim_next_does_not_duplicate_live_claim(monkeypatch) -> None:
    storage = {
        "status": "pending",
        "attempt": 0,
        "claim_token": None,
        "claimed_until_live": False,
    }
    executed: list[tuple[str, object]] = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            executed.append((sql, params))
            self._sql = " ".join(sql.split())
            self._params = params

        def fetchone(self):
            if "RETURNING jobs.job_key" not in self._sql:
                return None
            excludes_live_pending = (
                "claim_token IS NULL OR claimed_until IS NULL OR claimed_until <= now()"
                in self._sql
            )
            marks_running = "SET status = 'running'" in self._sql
            status = str(storage["status"])
            is_live = bool(storage["claimed_until_live"])
            if status == "pending" and is_live and excludes_live_pending:
                return None
            if status == "running" and is_live:
                return None
            storage["attempt"] = int(storage["attempt"]) + 1
            storage["status"] = "running" if marks_running else "pending"
            storage["claim_token"] = self._params[3]
            storage["claimed_until_live"] = True
            return {
                "job_key": "chat:conversation_title:thread-dup",
                "kind": "conversation_title",
                "payload": {"root_thread_id": "thread-dup", "user_id": "user-1"},
                "run_at": None,
                "max_attempts": 3,
                "dedupe_policy": "skip",
                "attempt": storage["attempt"],
                "claim_token": storage["claim_token"],
            }

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(
        "focus_agent.services.coordination.psycopg.connect",
        lambda uri, row_factory=None: FakeConnection(),
    )

    worker_a = PostgresBackgroundJobDeduperBackend(
        "postgresql://example",
        claim_ttl_seconds=30.0,
        owner="worker-a",
    )
    worker_b = PostgresBackgroundJobDeduperBackend(
        "postgresql://example",
        claim_ttl_seconds=30.0,
        owner="worker-b",
    )

    first_claimed = worker_a.claim_next_job(allowed_kinds=("conversation_title",))
    second_claimed = worker_b.claim_next_job(allowed_kinds=("conversation_title",))

    assert first_claimed is not None
    assert second_claimed is None
    statements = [" ".join(sql.split()) for sql, _ in executed]
    claim_statements = [
        statement for statement in statements if "RETURNING jobs.job_key" in statement
    ]
    assert claim_statements
    assert all(
        "SET status = 'running'" in statement
        or "claim_token IS NULL OR claimed_until IS NULL OR claimed_until <= now()" in statement
        for statement in claim_statements
    )


def test_postgres_background_job_claim_token_guards_stale_workers(monkeypatch) -> None:
    executed: list[tuple[str, object]] = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            executed.append((sql, params))

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(
        "focus_agent.services.coordination.psycopg.connect",
        lambda uri, row_factory=None: FakeConnection(),
    )

    backend = PostgresBackgroundJobDeduperBackend(
        "postgresql://example",
        owner="worker-old",
    )
    stale_claim = BackgroundJobClaim(claim_token="old-token", owner="worker-old", attempt=1)
    backend.release_job_claim("chat:branch_title:thread-1", stale_claim)

    statement = " ".join(executed[0][0].split())
    assert "claimed_by = %s" in statement
    assert "claim_token = %s" in statement
    assert "claimed_until > now()" in statement
    assert executed[0][1] == ("chat:branch_title:thread-1", "worker-old", "old-token")
