from __future__ import annotations

import time

from focus_agent.services.background_work import BoundedBackgroundQueue


def test_background_queue_deduplicates_pending_keys_and_tracks_metrics() -> None:
    calls: list[str] = []
    queue = BoundedBackgroundQueue(name="test", max_concurrency=1, max_size=2)
    try:
        assert queue.submit(key="thread-1", func=lambda: calls.append("thread-1"), delay_seconds=0.05)
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
    queue_a = BoundedBackgroundQueue(name="shared-a", max_concurrency=1, max_size=2, job_deduper=deduper)
    queue_b = BoundedBackgroundQueue(name="shared-b", max_concurrency=1, max_size=2, job_deduper=deduper)
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
    queue = BoundedBackgroundQueue(name="durable", max_concurrency=1, max_size=2, job_deduper=deduper)
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
