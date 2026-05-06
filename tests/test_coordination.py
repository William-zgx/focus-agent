from __future__ import annotations

import time

from focus_agent.services.coordination import (
    BackgroundJobClaim,
    BackgroundJobSpec,
    InMemoryThreadTurnLockBackend,
    PostgresBackgroundJobDeduperBackend,
    PostgresThreadTurnLockBackend,
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

    assert backend.acquire_thread_turn(thread_id="thread-expiring", owner="owner-a", ttl_seconds=0.001)
    time.sleep(0.01)
    assert backend.acquire_thread_turn(thread_id="thread-expiring", owner="owner-b", ttl_seconds=1.0)


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
    backend.mark_job_failed("chat:context_compaction:thread-1", "busy")
    backend.release_job_claim("chat:context_compaction:thread-1", claim)
    snapshot = backend.snapshot()

    statements = [" ".join(sql.split()) for sql, _ in executed]
    assert "INSERT INTO focus_background_jobs" in statements[0]
    assert "attempt = focus_background_jobs.attempt + 1" in statements[0]
    assert "claim_token = EXCLUDED.claim_token" in statements[0]
    assert "status = 'running'" in statements[1]
    assert "claim_token = %s" in statements[1]
    assert "WHEN attempt >= max_attempts THEN 'failed'" in statements[2]
    assert "ELSE 'pending'" in statements[2]
    assert "claim_token = %s" in statements[2]
    assert "status = 'released'" in statements[3]
    assert "claim_token = %s" in statements[3]
    assert executed[0][1][0] == "chat:context_compaction:thread-1"
    assert executed[0][1][1] == "context_compaction"
    assert executed[0][1][2] == "worker-1"
    assert isinstance(executed[0][1][4], str)
    assert executed[2][1] == ("busy", "chat:context_compaction:thread-1", "worker-1", "claim-token-1")
    assert snapshot["job_backend_durable"] == 1
    assert snapshot["job_pending_total"] == 1
    assert snapshot["job_failed_total"] == 1
    assert snapshot["job_attempt_total"] == 5


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
    assert "claim_token = %s" in statements[2]
    assert executed[0][1][0] == "chat:conversation_title:thread-1"
    assert executed[0][1][1] == "conversation_title"
    assert executed[0][1][4] == 3
    assert executed[2][1][0] == ["conversation_title"]
    assert executed[2][1][1] == "worker-1"


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
    assert executed[0][1] == ("chat:branch_title:thread-1", "worker-old", "old-token")
