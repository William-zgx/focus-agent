from __future__ import annotations

import logging
import threading
import time

from .chat_turn_errors import ConcurrentTurnError
from .coordination import ThreadTurnLease, ThreadTurnLockBackend, new_thread_turn_owner

logger = logging.getLogger("focus_agent.chat")


class ThreadTurnLeaseLost(ConcurrentTurnError):  # noqa: N818
    """Raised when a turn loses ownership of its thread lock mid-flight."""


class ThreadTurnLeaseManager:
    def __init__(
        self,
        *,
        backend: ThreadTurnLockBackend,
        thread_id: str,
        ttl_seconds: float,
        heartbeat_interval_seconds: float,
    ) -> None:
        self._backend = backend
        self.thread_id = thread_id
        self.ttl_seconds = max(float(ttl_seconds or 0.0), 0.001)
        self.heartbeat_interval_seconds = max(float(heartbeat_interval_seconds or 0.0), 0.001)
        self._lease: ThreadTurnLease | None = None
        self._heartbeat_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._condition = threading.Condition()
        self._lost_error: ThreadTurnLeaseLost | None = None
        self._closed = False

    def __enter__(self) -> ThreadTurnLeaseManager:
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback
        self.close()

    @property
    def lease(self) -> ThreadTurnLease | None:
        return self._lease

    @property
    def owner(self) -> str | None:
        return self._lease.owner if self._lease is not None else None

    @property
    def lost(self) -> bool:
        return self.lost_error is not None

    @property
    def lost_error(self) -> ThreadTurnLeaseLost | None:
        with self._condition:
            return self._lost_error

    def acquire(self) -> None:
        if self._lease is not None:
            return
        owner = new_thread_turn_owner()
        acquired = self._backend.acquire_thread_turn(
            thread_id=self.thread_id,
            owner=owner,
            ttl_seconds=self.ttl_seconds,
        )
        if not acquired:
            raise ConcurrentTurnError(
                "This thread is still processing the previous turn. "
                "Please wait for it to finish before sending another message."
            )
        self._lease = ThreadTurnLease(thread_id=self.thread_id, owner=owner)
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name=f"thread-turn-heartbeat:{self.thread_id}",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def close(self) -> None:
        lease = self._lease
        if lease is None:
            return
        self._stop_event.set()
        self._notify_changed()
        heartbeat_thread = self._heartbeat_thread
        if heartbeat_thread is not None and heartbeat_thread is not threading.current_thread():
            heartbeat_thread.join(timeout=min(max(self.heartbeat_interval_seconds, 0.1), 1.0))
        try:
            self._backend.release_thread_turn(thread_id=lease.thread_id, owner=lease.owner)
        finally:
            with self._condition:
                self._lease = None
                self._closed = True
                self._condition.notify_all()

    def heartbeat_once(self) -> bool:
        lease = self._lease
        if lease is None or self.lost:
            return False
        try:
            ok = self._backend.heartbeat_thread_turn(
                thread_id=lease.thread_id,
                owner=lease.owner,
                ttl_seconds=self.ttl_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("thread turn lock heartbeat failed", exc_info=True)
            self._mark_lost(
                ThreadTurnLeaseLost(
                    f"Thread turn lock heartbeat failed for thread {lease.thread_id}: {exc}"
                )
            )
            return False
        if not ok:
            self._mark_lost(
                ThreadTurnLeaseLost(
                    f"Thread turn lock heartbeat was lost for thread {lease.thread_id}."
                )
            )
            return False
        return True

    def raise_if_lost(self) -> None:
        error = self.lost_error
        if error is not None:
            raise error

    def wait_lost_or_closed(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + max(float(timeout), 0.0)
        with self._condition:
            while self._lost_error is None and not self._closed:
                if deadline is None:
                    self._condition.wait()
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
            return self._lost_error is not None

    def _heartbeat_loop(self) -> None:
        while not self._stop_event.wait(self.heartbeat_interval_seconds):
            if not self.heartbeat_once():
                return

    def _mark_lost(self, error: ThreadTurnLeaseLost) -> None:
        with self._condition:
            if self._lost_error is None:
                self._lost_error = error
            self._condition.notify_all()

    def _notify_changed(self) -> None:
        with self._condition:
            self._condition.notify_all()
