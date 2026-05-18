"""Maintenance hooks for multi-agent cleanup and watchdog jobs."""

from __future__ import annotations

import threading
import time
from typing import Any


class MultiAgentMaintenanceWorker:
    """Periodic best-effort maintenance loop for multi-agent coordination ports."""

    def __init__(
        self,
        coordination_backend: Any,
        *,
        lock_cleanup_interval_seconds: float = 60.0,
        message_cleanup_interval_seconds: float = 300.0,
        approval_timeout_interval_seconds: float = 60.0,
        deadlock_detection_interval_seconds: float = 30.0,
    ) -> None:
        self.coordination_backend = coordination_backend
        self.lock_cleanup_interval_seconds = _positive_interval(lock_cleanup_interval_seconds)
        self.message_cleanup_interval_seconds = _positive_interval(message_cleanup_interval_seconds)
        self.approval_timeout_interval_seconds = _positive_interval(
            approval_timeout_interval_seconds
        )
        self.deadlock_detection_interval_seconds = _positive_interval(
            deadlock_detection_interval_seconds
        )
        self._closed = threading.Event()
        self._lock = threading.Lock()
        self._last_run = {
            "expired_locks": 0.0,
            "expired_messages": 0.0,
            "timed_out_approvals": 0.0,
            "deadlocks": 0.0,
        }
        self._last_report: dict[str, Any] = {
            "expired_locks": 0,
            "expired_messages": 0,
            "timed_out_approvals": 0,
            "deadlocks": [],
        }
        self._thread = threading.Thread(
            target=self._loop,
            name="focus-agent-multi-agent-maintenance",
            daemon=True,
        )

    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()

    def close(self) -> None:
        self._closed.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._last_report)

    def run_once(self, *, force: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        resource_locks = getattr(self.coordination_backend, "resource_locks", None)
        message_bus = getattr(self.coordination_backend, "message_bus", None)
        approval_queue = getattr(self.coordination_backend, "approval_queue", None)

        report: dict[str, Any] = {
            "expired_locks": 0,
            "expired_messages": 0,
            "timed_out_approvals": 0,
            "deadlocks": [],
        }
        if force or _due(
            now,
            self._last_run["expired_locks"],
            self.lock_cleanup_interval_seconds,
        ):
            report["expired_locks"] = _call_int(resource_locks, "cleanup_expired")
            self._last_run["expired_locks"] = now
        if force or _due(
            now,
            self._last_run["expired_messages"],
            self.message_cleanup_interval_seconds,
        ):
            report["expired_messages"] = _call_int(message_bus, "cleanup_expired")
            self._last_run["expired_messages"] = now
        if force or _due(
            now,
            self._last_run["timed_out_approvals"],
            self.approval_timeout_interval_seconds,
        ):
            report["timed_out_approvals"] = _call_int(approval_queue, "expire_pending")
            self._last_run["timed_out_approvals"] = now
        if force or _due(
            now,
            self._last_run["deadlocks"],
            self.deadlock_detection_interval_seconds,
        ):
            report["deadlocks"] = _call_list(resource_locks, "detect_deadlocks")
            self._last_run["deadlocks"] = now

        with self._lock:
            self._last_report = report
        return report

    def _loop(self) -> None:
        while not self._closed.is_set():
            self.run_once()
            self._closed.wait(1.0)


def run_multi_agent_maintenance(coordination_backend: Any) -> dict[str, Any]:
    """Run one best-effort maintenance tick across optional multi-agent ports."""

    resource_locks = getattr(coordination_backend, "resource_locks", None)
    message_bus = getattr(coordination_backend, "message_bus", None)
    approval_queue = getattr(coordination_backend, "approval_queue", None)

    expired_locks = _call_int(resource_locks, "cleanup_expired")
    expired_messages = _call_int(message_bus, "cleanup_expired")
    timed_out_approvals = _call_int(approval_queue, "expire_pending")
    deadlocks = _call_list(resource_locks, "detect_deadlocks")

    return {
        "expired_locks": expired_locks,
        "expired_messages": expired_messages,
        "timed_out_approvals": timed_out_approvals,
        "deadlocks": deadlocks,
    }


def _call_int(target: Any, method_name: str) -> int:
    method = getattr(target, method_name, None)
    if not callable(method):
        return 0
    return int(method() or 0)


def _call_list(target: Any, method_name: str) -> list[Any]:
    method = getattr(target, method_name, None)
    if not callable(method):
        return []
    result = method()
    return list(result or [])


def _positive_interval(value: float) -> float:
    return max(float(value or 0.0), 0.001)


def _due(now: float, last_run: float, interval_seconds: float) -> bool:
    return last_run <= 0.0 or (now - last_run) >= interval_seconds


__all__ = ["MultiAgentMaintenanceWorker", "run_multi_agent_maintenance"]
