from __future__ import annotations

import threading
import time

import pytest

from focus_agent.services.background_work import (
    BackgroundJobHandlerRegistry,
    BoundedBackgroundQueue,
    DurableBackgroundWorker,
    register_default_background_job_handlers,
)
from focus_agent.services.coordination import (
    BackgroundJobClaim,
    BackgroundJobSpec,
    InMemoryBackgroundJobDeduperBackend,
)


def test_background_queue_deduplicates_pending_keys_and_tracks_metrics() -> None:
    calls: list[str] = []
    queue = BoundedBackgroundQueue(name="test", max_concurrency=1, max_size=2)
    try:
        assert queue.submit(
            key="thread-1", func=lambda: calls.append("thread-1"), delay_seconds=0.05
        )
        assert not queue.submit(key="thread-1", func=lambda: calls.append("duplicate"))

        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and not calls:
            time.sleep(0.01)

        snapshot = queue.snapshot()
        assert calls == ["thread-1"]
        assert snapshot["submitted_total"] == 1
        assert snapshot["deduplicated_total"] == 1
        assert snapshot["completed_total"] == 1
        assert snapshot["dropped_total"] == 0
    finally:
        queue.close()


def test_background_queue_drops_after_close() -> None:
    queue = BoundedBackgroundQueue(name="closed-test", max_concurrency=1, max_size=1)
    try:
        queue.close()
        assert not queue.submit(key="late", func=lambda: None)

        snapshot = queue.snapshot()
        assert snapshot["submitted_total"] == 0
        assert snapshot["dropped_total"] == 1
    finally:
        queue.close()


def test_background_queue_close_timeout_does_not_hang_on_blocked_task() -> None:
    started = threading.Event()
    release = threading.Event()
    queue = BoundedBackgroundQueue(name="blocked-close", max_concurrency=1, max_size=1)

    def blocked_task() -> None:
        started.set()
        release.wait()

    try:
        assert queue.submit(key="blocked", func=blocked_task)
        assert started.wait(timeout=1.0)

        before_close = time.monotonic()
        assert not queue.close(timeout=0.05)
        assert time.monotonic() - before_close < 0.5
        assert not queue.submit(key="late", func=lambda: None)
        assert queue.snapshot()["active_workers"] == 1

        release.set()
        assert queue.close(timeout=1.0)
        snapshot = queue.snapshot()
        assert snapshot["queue_depth"] == 0
        assert snapshot["active_workers"] == 0
        assert snapshot["completed_total"] == 1
    finally:
        release.set()
        queue.close(timeout=1.0)


def test_background_queue_close_drains_full_queue_and_releases_claims() -> None:
    class TrackingDeduper:
        def __init__(self) -> None:
            self.claimed: set[str] = set()
            self.released: list[str] = []
            self.lock = threading.Lock()

        def try_claim_job_key(self, key: str) -> bool:
            with self.lock:
                if key in self.claimed:
                    return False
                self.claimed.add(key)
                return True

        def release_job_key(self, key: str) -> None:
            with self.lock:
                self.claimed.discard(key)
                self.released.append(key)

    deduper = TrackingDeduper()
    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []
    queue = BoundedBackgroundQueue(
        name="full-close",
        max_concurrency=1,
        max_size=1,
        job_deduper=deduper,
    )

    def blocked_task() -> None:
        started.set()
        release.wait()
        calls.append("running")

    releaser = threading.Thread(
        target=lambda: (time.sleep(0.05), release.set()),
        daemon=True,
    )
    try:
        assert queue.submit(key="running", func=blocked_task)
        assert started.wait(timeout=1.0)
        assert queue.submit(key="queued", func=lambda: calls.append("queued"))
        assert queue.snapshot()["queue_depth"] == 1

        releaser.start()
        assert queue.close(timeout=1.0)
        releaser.join(timeout=1.0)

        assert calls == ["running", "queued"]
        assert deduper.claimed == set()
        assert deduper.released == ["running", "queued"]
        assert queue.snapshot()["active_workers"] == 0
    finally:
        release.set()
        queue.close(timeout=1.0)


def test_background_queue_close_joins_all_workers() -> None:
    worker_count = 3
    started_count = 0
    started_lock = threading.Lock()
    all_started = threading.Event()
    release = threading.Event()
    queue = BoundedBackgroundQueue(
        name="multi-worker-close",
        max_concurrency=worker_count,
        max_size=worker_count,
    )

    def blocked_task() -> None:
        nonlocal started_count
        with started_lock:
            started_count += 1
            if started_count == worker_count:
                all_started.set()
        release.wait()

    releaser = threading.Thread(
        target=lambda: (time.sleep(0.05), release.set()),
        daemon=True,
    )
    try:
        for index in range(worker_count):
            assert queue.submit(key=f"worker-{index}", func=blocked_task)
        assert all_started.wait(timeout=1.0)

        releaser.start()
        assert queue.close(timeout=1.0)
        releaser.join(timeout=1.0)

        assert all(not worker.is_alive() for worker in queue._workers)
        snapshot = queue.snapshot()
        assert snapshot["active_workers"] == 0
        assert snapshot["completed_total"] == worker_count
    finally:
        release.set()
        queue.close(timeout=1.0)


def test_background_queue_close_is_idempotent() -> None:
    calls: list[str] = []
    queue = BoundedBackgroundQueue(name="repeat-close", max_concurrency=2, max_size=2)
    try:
        assert queue.submit(key="once", func=lambda: calls.append("once"))

        assert queue.close(timeout=1.0)
        assert queue.close(timeout=0.01)

        assert calls == ["once"]
        assert all(not worker.is_alive() for worker in queue._workers)
        assert queue.snapshot()["active_workers"] == 0
    finally:
        queue.close(timeout=1.0)


def test_background_queue_uses_shared_job_deduper() -> None:
    class SharedDeduper:
        def __init__(self):
            self.keys: set[str] = set()

        def try_claim_job_key(self, key: str) -> bool:
            if key in self.keys:
                return False
            self.keys.add(key)
            return True

        def release_job_key(self, key: str) -> None:
            self.keys.discard(key)

    deduper = SharedDeduper()
    queue_a = BoundedBackgroundQueue(
        name="shared-a", max_concurrency=1, max_size=2, job_deduper=deduper
    )
    queue_b = BoundedBackgroundQueue(
        name="shared-b", max_concurrency=1, max_size=2, job_deduper=deduper
    )
    try:
        assert queue_a.submit(key="same-thread", func=lambda: None, delay_seconds=0.05)
        assert not queue_b.submit(key="same-thread", func=lambda: None, delay_seconds=0.05)
        assert queue_b.snapshot()["deduplicated_total"] == 1
    finally:
        queue_a.close()
        queue_b.close()


def test_background_queue_records_durable_job_lifecycle_and_snapshot() -> None:
    class DurableDeduper:
        durable = True

        def __init__(self):
            self.keys: set[str] = set()
            self.events: list[tuple[str, str]] = []

        def try_claim_job_key(self, key: str) -> bool:
            if key in self.keys:
                return False
            self.keys.add(key)
            self.events.append(("claim", key))
            return True

        def mark_job_running(self, key: str) -> None:
            self.events.append(("running", key))

        def mark_job_succeeded(self, key: str) -> None:
            self.events.append(("succeeded", key))

        def release_job_key(self, key: str) -> None:
            self.keys.discard(key)
            self.events.append(("release", key))

        def snapshot(self) -> dict[str, int]:
            return {
                "job_backend_durable": 1,
                "job_pending_total": len(self.keys),
                "job_succeeded_total": 1,
                "job_attempt_total": 1,
            }

    deduper = DurableDeduper()
    calls: list[str] = []
    queue = BoundedBackgroundQueue(
        name="durable", max_concurrency=1, max_size=2, job_deduper=deduper
    )
    try:
        assert queue.submit(key="job-1", func=lambda: calls.append("ran"))
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and not calls:
            time.sleep(0.01)

        snapshot = queue.snapshot()
        assert calls == ["ran"]
        assert ("claim", "job-1") in deduper.events
        assert ("running", "job-1") in deduper.events
        assert ("succeeded", "job-1") in deduper.events
        assert ("release", "job-1") in deduper.events
        assert snapshot["completed_total"] == 1
        assert snapshot["job_backend_durable"] == 1
        assert snapshot["job_succeeded_total"] == 1
        assert snapshot["job_attempt_total"] == 1
    finally:
        queue.close()


def test_background_queue_uses_claim_token_lifecycle_when_backend_supports_it() -> None:
    class ClaimingDeduper:
        def __init__(self):
            self.claim = BackgroundJobClaim(claim_token="claim-1", owner="worker-1", attempt=1)
            self.events: list[tuple[str, str, str]] = []

        def claim_job_key(self, key: str):
            self.events.append(("claim", key, self.claim.claim_token))
            return self.claim

        def try_claim_job_key(self, key: str) -> bool:
            return False

        def mark_job_claim_running(self, key: str, claim: BackgroundJobClaim) -> None:
            self.events.append(("running", key, claim.claim_token))

        def mark_job_claim_succeeded(self, key: str, claim: BackgroundJobClaim) -> None:
            self.events.append(("succeeded", key, claim.claim_token))

        def release_job_claim(self, key: str, claim: BackgroundJobClaim) -> None:
            self.events.append(("release", key, claim.claim_token))

        def release_job_key(self, key: str) -> None:
            self.events.append(("release-key", key, ""))

    deduper = ClaimingDeduper()
    calls: list[str] = []
    queue = BoundedBackgroundQueue(
        name="claiming", max_concurrency=1, max_size=2, job_deduper=deduper
    )
    try:
        assert queue.submit(key="job-claim", func=lambda: calls.append("ran"))
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and not calls:
            time.sleep(0.01)

        assert calls == ["ran"]
        assert ("claim", "job-claim", "claim-1") in deduper.events
        assert ("running", "job-claim", "claim-1") in deduper.events
        assert ("succeeded", "job-claim", "claim-1") in deduper.events
        assert ("release", "job-claim", "claim-1") in deduper.events
        assert not any(event[0] == "release-key" for event in deduper.events)
    finally:
        queue.close()


def test_durable_background_handler_registry_rejects_unregistered_kinds() -> None:
    registry = BackgroundJobHandlerRegistry()
    registry.register("context_compaction", lambda payload: None)

    assert registry.kinds() == ("context_compaction",)
    assert registry.get("context_compaction") is not None
    with pytest.raises(ValueError):
        registry.register("arbitrary_python_callable", lambda payload: None)


def test_durable_background_worker_runs_registered_handler_with_claim() -> None:
    claim = BackgroundJobClaim(claim_token="claim-1", owner="worker-1", attempt=1)
    spec = BackgroundJobSpec(
        kind="conversation_title",
        key="chat:conversation_title:thread-1",
        payload={"root_thread_id": "thread-1", "user_id": "user-1"},
        max_attempts=2,
    )

    class Backend:
        def __init__(self):
            self.claimed = False
            self.events: list[tuple[str, str, str]] = []

        def claim_next_job(self, *, allowed_kinds, claim_ttl_seconds=None):
            assert tuple(allowed_kinds) == ("conversation_title",)
            if self.claimed:
                return None
            self.claimed = True
            return spec, claim

        def mark_job_claim_running(self, key: str, job_claim: BackgroundJobClaim) -> None:
            self.events.append(("running", key, job_claim.claim_token))

        def mark_job_claim_succeeded(self, key: str, job_claim: BackgroundJobClaim) -> None:
            self.events.append(("succeeded", key, job_claim.claim_token))

        def mark_job_claim_failed(
            self, key: str, job_claim: BackgroundJobClaim, error: str
        ) -> None:
            self.events.append(("failed", key, job_claim.claim_token))

    backend = Backend()
    calls: list[dict[str, str]] = []
    registry = BackgroundJobHandlerRegistry(
        {
            "conversation_title": lambda payload: calls.append(dict(payload)),
        }
    )
    worker = DurableBackgroundWorker(name="test", job_backend=backend, handlers=registry)

    assert worker.run_once()
    assert not worker.run_once()
    assert calls == [{"root_thread_id": "thread-1", "user_id": "user-1"}]
    assert backend.events == [
        ("running", "chat:conversation_title:thread-1", "claim-1"),
        ("succeeded", "chat:conversation_title:thread-1", "claim-1"),
    ]
    assert worker.snapshot()["durable_worker_completed_total"] == 1


def test_durable_background_worker_heartbeats_long_handler_claim() -> None:
    claim = BackgroundJobClaim(claim_token="claim-heartbeat", owner="worker-1", attempt=1)
    spec = BackgroundJobSpec(
        kind="conversation_title",
        key="chat:conversation_title:thread-heartbeat",
        payload={"root_thread_id": "thread-heartbeat", "user_id": "user-1"},
        max_attempts=2,
    )

    class Backend:
        def __init__(self):
            self.claimed = False
            self.heartbeat_seen = False
            self.events: list[tuple[str, str, str]] = []

        def claim_next_job(self, *, allowed_kinds, claim_ttl_seconds=None):
            if self.claimed:
                return None
            self.claimed = True
            return spec, claim

        def mark_job_claim_running(self, key: str, job_claim: BackgroundJobClaim) -> None:
            self.events.append(("running", key, job_claim.claim_token))

        def heartbeat_job_claim(
            self, key: str, job_claim: BackgroundJobClaim, ttl_seconds: float
        ) -> bool:
            self.heartbeat_seen = True
            self.events.append(("heartbeat", key, job_claim.claim_token))
            return True

        def mark_job_claim_succeeded(self, key: str, job_claim: BackgroundJobClaim) -> None:
            self.events.append(("succeeded", key, job_claim.claim_token))

        def mark_job_claim_failed(
            self, key: str, job_claim: BackgroundJobClaim, error: str
        ) -> None:
            self.events.append(("failed", key, job_claim.claim_token))

    backend = Backend()

    def handler(payload):
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and not backend.heartbeat_seen:
            time.sleep(0.01)
        assert backend.heartbeat_seen

    registry = BackgroundJobHandlerRegistry({"conversation_title": handler})
    worker = DurableBackgroundWorker(
        name="heartbeat",
        job_backend=backend,
        handlers=registry,
        claim_ttl_seconds=0.15,
    )

    assert worker.run_once()
    assert (
        "heartbeat",
        "chat:conversation_title:thread-heartbeat",
        "claim-heartbeat",
    ) in backend.events
    assert (
        "succeeded",
        "chat:conversation_title:thread-heartbeat",
        "claim-heartbeat",
    ) in backend.events
    assert not any(event[0] == "failed" for event in backend.events)
    assert worker.snapshot()["durable_worker_completed_total"] == 1


def test_durable_background_worker_does_not_succeed_when_heartbeat_is_lost() -> None:
    claim = BackgroundJobClaim(claim_token="claim-lost", owner="worker-1", attempt=1)
    spec = BackgroundJobSpec(
        kind="conversation_title",
        key="chat:conversation_title:thread-lost",
        payload={"root_thread_id": "thread-lost", "user_id": "user-1"},
        max_attempts=2,
    )

    class Backend:
        def __init__(self):
            self.claimed = False
            self.heartbeat_seen = False
            self.events: list[tuple[str, str, str, str]] = []

        def claim_next_job(self, *, allowed_kinds, claim_ttl_seconds=None):
            if self.claimed:
                return None
            self.claimed = True
            return spec, claim

        def mark_job_claim_running(self, key: str, job_claim: BackgroundJobClaim) -> None:
            self.events.append(("running", key, job_claim.claim_token, ""))

        def heartbeat_job_claim(
            self, key: str, job_claim: BackgroundJobClaim, ttl_seconds: float
        ) -> bool:
            self.heartbeat_seen = True
            self.events.append(("heartbeat", key, job_claim.claim_token, ""))
            return False

        def mark_job_claim_succeeded(self, key: str, job_claim: BackgroundJobClaim) -> None:
            self.events.append(("succeeded", key, job_claim.claim_token, ""))

        def mark_job_claim_failed(
            self, key: str, job_claim: BackgroundJobClaim, error: str
        ) -> None:
            self.events.append(("failed", key, job_claim.claim_token, error))

    backend = Backend()

    def handler(payload):
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and not backend.heartbeat_seen:
            time.sleep(0.01)
        assert backend.heartbeat_seen

    registry = BackgroundJobHandlerRegistry({"conversation_title": handler})
    worker = DurableBackgroundWorker(
        name="heartbeat-lost",
        job_backend=backend,
        handlers=registry,
        claim_ttl_seconds=0.15,
    )

    assert worker.run_once()
    assert not any(event[0] == "succeeded" for event in backend.events)
    failed = [event for event in backend.events if event[0] == "failed"]
    assert failed
    assert "heartbeat lost" in failed[0][3]
    snapshot = worker.snapshot()
    assert snapshot["durable_worker_completed_total"] == 0
    assert snapshot["durable_worker_failed_total"] == 1
    assert snapshot["durable_worker_heartbeat_lost_total"] == 1


def test_durable_background_worker_retries_then_dead_letters_failed_jobs() -> None:
    backend = InMemoryBackgroundJobDeduperBackend(retry_base_delay_seconds=0.0)
    spec = BackgroundJobSpec(
        kind="conversation_title",
        key="chat:conversation_title:thread-retry",
        payload={"root_thread_id": "thread-retry", "user_id": "user-1"},
        max_attempts=2,
    )
    registry = BackgroundJobHandlerRegistry(
        {
            "conversation_title": lambda payload: (_ for _ in ()).throw(RuntimeError("boom")),
        }
    )
    worker = DurableBackgroundWorker(name="retry", job_backend=backend, handlers=registry)

    assert backend.enqueue_job(spec)
    assert worker.run_once()
    snapshot = backend.snapshot()
    assert snapshot["job_retrying_total"] == 1
    assert snapshot["job_dead_lettered_total"] == 0

    assert worker.run_once()
    snapshot = backend.snapshot()
    assert snapshot["job_retrying_total"] == 0
    assert snapshot["job_dead_lettered_total"] == 1
    assert worker.snapshot()["durable_worker_failed_total"] == 2


def test_default_durable_handlers_call_fixed_service_methods() -> None:
    class ChatService:
        def __init__(self):
            self.calls: list[dict[str, object]] = []

        def compact_thread_context(self, **kwargs):
            self.calls.append(kwargs)

    class BranchService:
        def __init__(self):
            self.calls: list[tuple[str, dict[str, str]]] = []

        def refresh_conversation_title_after_first_turn(self, **kwargs):
            self.calls.append(("conversation_title", kwargs))

        def refresh_branch_metadata_after_first_turn(self, **kwargs):
            self.calls.append(("branch_title", kwargs))

    chat_service = ChatService()
    branch_service = BranchService()
    registry = BackgroundJobHandlerRegistry()

    register_default_background_job_handlers(
        registry,
        chat_service=chat_service,
        branch_service=branch_service,
    )

    registry.get("context_compaction")(
        {"thread_id": "thread-1", "user_id": "user-1", "trigger": "auto_post_turn"}
    )
    registry.get("conversation_title")({"root_thread_id": "root-1", "user_id": "user-1"})
    registry.get("branch_title")({"child_thread_id": "child-1", "user_id": "user-1"})

    assert chat_service.calls == [
        {
            "thread_id": "thread-1",
            "user_id": "user-1",
            "trigger": "auto_post_turn",
            "force": False,
        }
    ]
    assert branch_service.calls == [
        ("conversation_title", {"root_thread_id": "root-1", "user_id": "user-1"}),
        ("branch_title", {"child_thread_id": "child-1", "user_id": "user-1"}),
    ]
