from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
import queue
import threading
import time
from typing import Any

from .coordination import BackgroundJobDeduperBackend, InMemoryBackgroundJobDeduperBackend

logger = logging.getLogger("focus_agent.background")


@dataclass(frozen=True, slots=True)
class BackgroundTask:
    key: str
    func: Callable[..., Any]
    kwargs: dict[str, Any]
    run_at: float


class BoundedBackgroundQueue:
    """Small bounded worker queue for best-effort post-turn jobs."""

    def __init__(
        self,
        *,
        name: str,
        max_concurrency: int = 2,
        max_size: int = 1000,
        job_deduper: BackgroundJobDeduperBackend | None = None,
    ) -> None:
        self.name = name
        self.max_concurrency = max(1, int(max_concurrency or 1))
        self.max_size = max(1, int(max_size or 1))
        self._queue: queue.Queue[BackgroundTask | None] = queue.Queue(maxsize=self.max_size)
        self._lock = threading.Lock()
        self._job_deduper = job_deduper or InMemoryBackgroundJobDeduperBackend()
        self._closed = False
        self._active_workers = 0
        self._submitted_total = 0
        self._deduplicated_total = 0
        self._dropped_total = 0
        self._completed_total = 0
        self._failed_total = 0
        self._workers = [
            threading.Thread(
                target=self._worker,
                name=f"focus-agent-background-{name}-{index + 1}",
                daemon=True,
            )
            for index in range(self.max_concurrency)
        ]
        for worker in self._workers:
            worker.start()

    def submit(
        self,
        *,
        key: str,
        func: Callable[..., Any],
        delay_seconds: float = 0.0,
        **kwargs: Any,
    ) -> bool:
        task_key = str(key or "background:anonymous")
        with self._lock:
            if self._closed:
                self._dropped_total += 1
                return False
            if not self._job_deduper.try_claim_job_key(task_key):
                self._deduplicated_total += 1
                return False
        task = BackgroundTask(
            key=task_key,
            func=func,
            kwargs=dict(kwargs),
            run_at=time.monotonic() + max(float(delay_seconds or 0.0), 0.0),
        )
        try:
            self._queue.put_nowait(task)
        except queue.Full:
            self._job_deduper.release_job_key(task_key)
            with self._lock:
                self._dropped_total += 1
            return False
        with self._lock:
            self._submitted_total += 1
        return True

    def snapshot(self) -> dict[str, int]:
        job_metrics: dict[str, int] = {}
        snapshot_backend = getattr(self._job_deduper, "snapshot", None)
        if callable(snapshot_backend):
            try:
                job_metrics = {str(key): int(value) for key, value in dict(snapshot_backend()).items()}
            except Exception:  # noqa: BLE001 - metrics must not break health scrapes
                logger.warning("background job backend snapshot failed", exc_info=True)
                job_metrics = {"job_backend_error": 1}
        with self._lock:
            return {
                "queue_depth": self._queue.qsize(),
                "active_workers": self._active_workers,
                "max_concurrency": self.max_concurrency,
                "max_size": self.max_size,
                "submitted_total": self._submitted_total,
                "deduplicated_total": self._deduplicated_total,
                "dropped_total": self._dropped_total,
                "completed_total": self._completed_total,
                "failed_total": self._failed_total,
                **job_metrics,
            }

    def close(self) -> None:
        with self._lock:
            self._closed = True
        for _worker in self._workers:
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                break

    def release_job_key(self, key: str) -> None:
        self._job_deduper.release_job_key(str(key or "background:anonymous"))

    def _worker(self) -> None:
        while True:
            task = self._queue.get()
            if task is None:
                self._queue.task_done()
                return
            try:
                delay = task.run_at - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                self._mark_job_running(task.key)
                with self._lock:
                    self._active_workers += 1
                try:
                    task.func(**task.kwargs)
                except Exception as exc:  # noqa: BLE001 - best-effort background work must not break turns
                    logger.warning("background task failed", extra={"task_key": task.key}, exc_info=True)
                    self._mark_job_failed(task.key, str(exc))
                    with self._lock:
                        self._failed_total += 1
                else:
                    self._mark_job_succeeded(task.key)
                    with self._lock:
                        self._completed_total += 1
            finally:
                self._job_deduper.release_job_key(task.key)
                with self._lock:
                    if self._active_workers > 0:
                        self._active_workers -= 1
                self._queue.task_done()

    def _mark_job_running(self, key: str) -> None:
        marker = getattr(self._job_deduper, "mark_job_running", None)
        if callable(marker):
            marker(key)

    def _mark_job_succeeded(self, key: str) -> None:
        marker = getattr(self._job_deduper, "mark_job_succeeded", None)
        if callable(marker):
            marker(key)

    def _mark_job_failed(self, key: str, error: str) -> None:
        marker = getattr(self._job_deduper, "mark_job_failed", None)
        if callable(marker):
            marker(key, error)


__all__ = ["BackgroundTask", "BoundedBackgroundQueue"]
