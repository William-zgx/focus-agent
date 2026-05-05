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
