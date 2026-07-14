from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ..core.repo_call import has_repo_method
from .coordination import (
    BackgroundJobClaim,
    BackgroundJobDeduperBackend,
    InMemoryBackgroundJobDeduperBackend,
)

logger = logging.getLogger("focus_agent.background")

REGISTERED_BACKGROUND_JOB_KINDS = frozenset(
    {
        "agent_team_run_session",
        "agent_team_run_task",
        "memory_embedding",
        "context_compaction",
        "conversation_title",
        "branch_title",
        "branch_decision_evaluate",
    }
)


def _invoke_job_backend_hook(
    backend: Any,
    key: str,
    claim: BackgroundJobClaim | None,
    claim_hook: str,
    fallback_hook: str,
    *args: Any,
) -> None:
    if claim is not None:
        if has_repo_method(backend, claim_hook):
            getattr(backend, claim_hook)(key, claim, *args)
            return
    if has_repo_method(backend, fallback_hook):
        getattr(backend, fallback_hook)(key, *args)


@dataclass(frozen=True, slots=True)
class BackgroundTask:
    key: str
    func: Callable[..., Any]
    kwargs: dict[str, Any]
    run_at: float
    claim: BackgroundJobClaim | None = None


BackgroundJobHandler = Callable[[dict[str, Any]], Any]


class _DurableJobClaimLostError(RuntimeError):
    pass


class BackgroundJobHandlerRegistry:
    """Registry for durable job kinds that are safe to replay by name."""

    def __init__(self, handlers: Mapping[str, BackgroundJobHandler] | None = None) -> None:
        self._lock = threading.Lock()
        self._handlers: dict[str, BackgroundJobHandler] = {}
        for kind, handler in dict(handlers or {}).items():
            self.register(kind, handler)

    def register(self, kind: str, handler: BackgroundJobHandler) -> None:
        normalized = str(kind or "").strip()
        if normalized not in REGISTERED_BACKGROUND_JOB_KINDS:
            raise ValueError(f"unsupported durable background job kind: {normalized}")
        if not callable(handler):
            raise TypeError("background job handler must be callable")
        with self._lock:
            self._handlers[normalized] = handler

    def get(self, kind: str) -> BackgroundJobHandler | None:
        with self._lock:
            return self._handlers.get(str(kind or "").strip())

    def kinds(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._handlers))


def register_default_background_job_handlers(
    registry: BackgroundJobHandlerRegistry,
    *,
    chat_service: Any | None = None,
    branch_service: Any | None = None,
    agent_team_service: Any | None = None,
    branch_decision_service: Any | None = None,
    memory_embedding_service: Any | None = None,
    memory_repository: Any | None = None,
) -> None:
    def _register(
        kind: str, handler: Any, payload_factory: Callable[[dict[str, Any]], dict[str, Any]]
    ) -> None:
        if not callable(handler):
            return
        registry.register(
            kind,
            lambda payload, handler=handler: handler(**payload_factory(payload)),
        )

    if agent_team_service is not None:
        _register(
            "agent_team_run_session",
            getattr(agent_team_service, "run_ready_tasks_once", None),
            lambda payload: {
                "session_id": _required_payload_string(payload, "session_id"),
                "user_id": _required_payload_string(payload, "user_id"),
            },
        )
        _register(
            "agent_team_run_task",
            getattr(agent_team_service, "run_task_claimed", None),
            lambda payload: {
                "task_id": _required_payload_string(payload, "task_id"),
                "user_id": _required_payload_string(payload, "user_id"),
            },
        )
    if chat_service is not None:
        _register(
            "context_compaction",
            getattr(chat_service, "compact_thread_context", None),
            lambda payload: {
                "thread_id": _required_payload_string(payload, "thread_id"),
                "user_id": _required_payload_string(payload, "user_id"),
                "trigger": str(payload.get("trigger") or "auto_post_turn"),
                "force": bool(payload.get("force", False)),
            },
        )
    if branch_service is not None:
        _register(
            "conversation_title",
            getattr(branch_service, "refresh_conversation_title_after_first_turn", None),
            lambda payload: {
                "root_thread_id": _required_payload_string(payload, "root_thread_id"),
                "user_id": _required_payload_string(payload, "user_id"),
            },
        )
        branch_title_handler = getattr(
            branch_service, "refresh_branch_metadata_after_first_turn", None
        )
        if branch_title_handler is None:
            branch_title_handler = getattr(
                branch_service, "refresh_branch_name_after_first_turn", None
            )
        _register(
            "branch_title",
            branch_title_handler,
            lambda payload: {
                "child_thread_id": _required_payload_string(payload, "child_thread_id"),
                "user_id": _required_payload_string(payload, "user_id"),
            },
        )
    if branch_decision_service is not None:
        _register(
            "branch_decision_evaluate",
            getattr(branch_decision_service, "evaluate_thread_turn", None),
            lambda payload: {
                "thread_id": _required_payload_string(payload, "thread_id"),
                "user_id": _required_payload_string(payload, "user_id"),
                "root_thread_id": str(payload.get("root_thread_id") or "") or None,
                "request_id": str(payload.get("request_id") or "") or None,
                "trace_id": str(payload.get("trace_id") or "") or None,
            },
        )
    if memory_embedding_service is not None and memory_repository is not None:
        from ..memory.embedding_worker import MemoryEmbeddingWorker

        worker = MemoryEmbeddingWorker(
            repository=memory_repository,
            embedding_service=memory_embedding_service,
        )
        _register(
            "memory_embedding",
            worker.process_payload,
            lambda payload: {
                "memory_id": _required_payload_string(payload, "memory_id"),
                "namespace": _required_payload_namespace(payload),
                "attempt": int(payload.get("_attempt") or 1),
                "max_attempts": int(payload.get("_max_attempts") or 3),
            },
        )


class DurableBackgroundWorker:
    """Polls durable job specs and dispatches registered fixed-kind handlers."""

    def __init__(
        self,
        *,
        name: str,
        job_backend: Any,
        handlers: BackgroundJobHandlerRegistry,
        poll_interval_seconds: float = 1.0,
        claim_ttl_seconds: float | None = None,
    ) -> None:
        self.name = name
        self._job_backend = job_backend
        self._handlers = handlers
        self._poll_interval_seconds = max(float(poll_interval_seconds or 0.0), 0.05)
        self._claim_ttl_seconds = claim_ttl_seconds
        self._closed = threading.Event()
        self._lock = threading.Lock()
        self._active = 0
        self._claimed_total = 0
        self._completed_total = 0
        self._failed_total = 0
        self._heartbeat_lost_total = 0
        self._claim_error_total = 0
        self._consecutive_claim_errors = 0
        self._started_at: float | None = None
        self._last_heartbeat_at: float | None = None
        self._thread = threading.Thread(
            target=self._loop,
            name=f"focus-agent-durable-background-{name}",
            daemon=True,
        )

    def start(self) -> None:
        with self._lock:
            if self._started_at is not None:
                return
            now = time.monotonic()
            self._started_at = now
            self._last_heartbeat_at = now
            self._thread.start()

    def close(self) -> None:
        self._closed.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def run_once(self) -> bool:
        if not has_repo_method(self._job_backend, "claim_next_job"):
            return False
        claimed = self._job_backend.claim_next_job(
            allowed_kinds=self._handlers.kinds(),
            claim_ttl_seconds=self._claim_ttl_seconds,
        )
        if claimed is None:
            return False
        spec, claim = claimed
        with self._lock:
            self._claimed_total += 1
            self._active += 1
        heartbeat: (
            tuple[str, BackgroundJobClaim, threading.Event, threading.Event, threading.Thread]
            | None
        ) = None
        try:
            self._mark_job_running(spec.key, claim)
            handler = self._handlers.get(spec.kind)
            if handler is None:
                raise KeyError(f"unregistered durable background job kind: {spec.kind}")
            heartbeat = self._start_job_claim_heartbeat(spec.key, claim)
            payload = dict(spec.payload)
            if spec.kind == "memory_embedding":
                payload["_attempt"] = claim.attempt
                payload["_max_attempts"] = spec.max_attempts
            handler(payload)
            if not self._stop_job_claim_heartbeat(heartbeat):
                raise _DurableJobClaimLostError("durable background job claim heartbeat lost")
        except Exception as exc:  # noqa: BLE001 - durable worker records and moves to the next job
            heartbeat_lost = not self._stop_job_claim_heartbeat(heartbeat, confirm=False)
            error = str(exc)
            if heartbeat_lost and not isinstance(exc, _DurableJobClaimLostError):
                error = f"{error}; durable background job claim heartbeat lost"
            logger.warning(
                "durable background job failed",
                extra={"job_key": spec.key, "job_kind": spec.kind},
                exc_info=True,
            )
            self._mark_job_failed(spec.key, claim, error)
            with self._lock:
                self._failed_total += 1
                if heartbeat_lost or isinstance(exc, _DurableJobClaimLostError):
                    self._heartbeat_lost_total += 1
        else:
            self._mark_job_succeeded(spec.key, claim)
            with self._lock:
                self._completed_total += 1
        finally:
            self._stop_job_claim_heartbeat(heartbeat, confirm=False)
            with self._lock:
                if self._active > 0:
                    self._active -= 1
        return True

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            snapshot = {
                "durable_worker_active": self._active,
                "durable_worker_claimed_total": self._claimed_total,
                "durable_worker_completed_total": self._completed_total,
                "durable_worker_failed_total": self._failed_total,
                "durable_worker_heartbeat_lost_total": self._heartbeat_lost_total,
                "durable_worker_claim_error_total": self._claim_error_total,
                "durable_worker_consecutive_claim_errors": self._consecutive_claim_errors,
            }
        health = self._health_snapshot()
        snapshot.update(
            {
                "durable_worker_started": int(health["started"]),
                "durable_worker_thread_alive": int(health["thread_alive"]),
                "durable_worker_heartbeat_age_seconds": int(health["heartbeat_age_seconds"]),
                "durable_worker_heartbeat_fresh": int(health["heartbeat_fresh"]),
            }
        )
        return snapshot

    def _loop(self) -> None:
        while not self._closed.is_set():
            self._record_heartbeat()
            try:
                processed = self.run_once()
            except Exception:  # noqa: BLE001 - claim failures must not kill the worker thread
                delay = self._record_claim_error()
                logger.warning("durable background job claim failed", exc_info=True)
                self._closed.wait(delay)
                continue
            self._clear_claim_errors()
            if not processed:
                self._closed.wait(self._poll_interval_seconds)

    def _record_heartbeat(self) -> None:
        with self._lock:
            self._last_heartbeat_at = time.monotonic()

    def _record_claim_error(self) -> float:
        with self._lock:
            self._claim_error_total += 1
            self._consecutive_claim_errors += 1
            self._last_heartbeat_at = time.monotonic()
            return min(
                self._poll_interval_seconds * (2 ** min(self._consecutive_claim_errors - 1, 6)),
                5.0,
            )

    def _clear_claim_errors(self) -> None:
        with self._lock:
            self._consecutive_claim_errors = 0

    def _health_snapshot(self) -> dict[str, bool | float]:
        with self._lock:
            started_at = self._started_at
            heartbeat_at = self._last_heartbeat_at
        if started_at is None or heartbeat_at is None:
            return {
                "started": False,
                "thread_alive": False,
                "heartbeat_age_seconds": 0.0,
                "heartbeat_fresh": False,
                "healthy": False,
            }
        heartbeat_age_seconds = max(time.monotonic() - heartbeat_at, 0.0)
        heartbeat_fresh = heartbeat_age_seconds <= self._heartbeat_stale_after_seconds()
        thread_alive = self._thread.is_alive()
        return {
            "started": True,
            "thread_alive": thread_alive,
            "heartbeat_age_seconds": heartbeat_age_seconds,
            "heartbeat_fresh": heartbeat_fresh,
            "healthy": thread_alive and heartbeat_fresh,
        }

    def _heartbeat_stale_after_seconds(self) -> float:
        return max(self._poll_interval_seconds * 3.0, 10.0)

    def _mark_job_running(self, key: str, claim: BackgroundJobClaim) -> None:
        _invoke_job_backend_hook(
            self._job_backend,
            key,
            claim,
            "mark_job_claim_running",
            "mark_job_running",
        )

    def _mark_job_succeeded(self, key: str, claim: BackgroundJobClaim) -> None:
        _invoke_job_backend_hook(
            self._job_backend,
            key,
            claim,
            "mark_job_claim_succeeded",
            "mark_job_succeeded",
        )

    def _mark_job_failed(self, key: str, claim: BackgroundJobClaim, error: str) -> None:
        _invoke_job_backend_hook(
            self._job_backend,
            key,
            claim,
            "mark_job_claim_failed",
            "mark_job_failed",
            error,
        )

    def _claim_heartbeat_ttl_seconds(self) -> float:
        if self._claim_ttl_seconds is not None:
            return max(float(self._claim_ttl_seconds or 0.0), 0.001)
        backend_ttl = getattr(self._job_backend, "claim_ttl_seconds", 300.0)
        return max(float(backend_ttl or 300.0), 0.001)

    def _claim_heartbeat_interval_seconds(self) -> float:
        return min(max(self._claim_heartbeat_ttl_seconds() / 3.0, 0.05), 5.0)

    def _heartbeat_job_claim(self, key: str, claim: BackgroundJobClaim) -> bool:
        if not has_repo_method(self._job_backend, "heartbeat_job_claim"):
            return True
        try:
            alive = bool(
                self._job_backend.heartbeat_job_claim(
                    key, claim, self._claim_heartbeat_ttl_seconds()
                )
            )
            if alive:
                self._record_heartbeat()
            return alive
        except Exception:  # noqa: BLE001 - heartbeat failures must not mark success
            logger.warning(
                "durable background job heartbeat failed", extra={"job_key": key}, exc_info=True
            )
            return False

    def _start_job_claim_heartbeat(
        self,
        key: str,
        claim: BackgroundJobClaim,
    ) -> tuple[str, BackgroundJobClaim, threading.Event, threading.Event, threading.Thread] | None:
        if not has_repo_method(self._job_backend, "heartbeat_job_claim"):
            return None
        stop_event = threading.Event()
        lost_event = threading.Event()
        interval = self._claim_heartbeat_interval_seconds()

        def run() -> None:
            while not stop_event.wait(interval):
                if not self._heartbeat_job_claim(key, claim):
                    lost_event.set()
                    return

        thread = threading.Thread(
            target=run,
            name=f"focus-agent-durable-background-heartbeat-{self.name}",
            daemon=True,
        )
        thread.start()
        return key, claim, stop_event, lost_event, thread

    def _stop_job_claim_heartbeat(
        self,
        heartbeat: tuple[
            str, BackgroundJobClaim, threading.Event, threading.Event, threading.Thread
        ]
        | None,
        *,
        confirm: bool = True,
    ) -> bool:
        if heartbeat is None:
            return True
        key, claim, stop_event, lost_event, thread = heartbeat
        stop_event.set()
        if thread.is_alive():
            thread.join(timeout=1.0)
        if thread.is_alive():
            return False
        if lost_event.is_set():
            return False
        if confirm:
            return self._heartbeat_job_claim(key, claim)
        return True


class BoundedBackgroundQueue:
    """Small bounded worker queue that drains accepted jobs during shutdown."""

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
        self._job_claims: dict[str, BackgroundJobClaim] = {}
        self._closed = False
        self._shutdown_complete = threading.Event()
        self._shutdown_thread: threading.Thread | None = None
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
        claim: BackgroundJobClaim | None = None
        release_claim = False
        with self._lock:
            if self._closed:
                self._dropped_total += 1
                return False
            if has_repo_method(self._job_deduper, "claim_job_key"):
                claim = self._job_deduper.claim_job_key(task_key)
                claimed = claim is not None
            else:
                claimed = self._job_deduper.try_claim_job_key(task_key)
            if not claimed:
                self._deduplicated_total += 1
                return False
            if claim is not None:
                self._job_claims[task_key] = claim
            task = BackgroundTask(
                key=task_key,
                func=func,
                kwargs=dict(kwargs),
                run_at=time.monotonic() + max(float(delay_seconds or 0.0), 0.0),
                claim=claim,
            )
            try:
                self._queue.put_nowait(task)
            except queue.Full:
                self._remove_job_claim(task_key, claim)
                self._dropped_total += 1
                release_claim = True
            else:
                self._submitted_total += 1
                return True
        if release_claim:
            self._release_job_claim(task_key, claim)
        return False

    def snapshot(self) -> dict[str, int]:
        job_metrics: dict[str, int] = {}
        if has_repo_method(self._job_deduper, "snapshot"):
            try:
                job_metrics = {
                    str(key): int(value)
                    for key, value in dict(self._job_deduper.snapshot()).items()
                }
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

    def close(self, timeout: float = 1.0) -> bool:
        """Stop accepting jobs and wait up to timeout while accepted jobs drain."""

        with self._lock:
            self._closed = True
            if self._shutdown_thread is None:
                self._shutdown_thread = threading.Thread(
                    target=self._shutdown,
                    name=f"focus-agent-background-{self.name}-shutdown",
                    daemon=True,
                )
                self._shutdown_thread.start()
        return self._shutdown_complete.wait(timeout=max(float(timeout), 0.0))

    def _shutdown(self) -> None:
        for _worker in self._workers:
            self._queue.put(None)
        self._queue.join()
        for worker in self._workers:
            worker.join()
        self._shutdown_complete.set()

    def release_job_key(self, key: str) -> None:
        task_key = str(key or "background:anonymous")
        with self._lock:
            claim = self._job_claims.pop(task_key, None)
        self._release_job_claim(task_key, claim)

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
                self._mark_job_running(task.key, task.claim)
                with self._lock:
                    self._active_workers += 1
                try:
                    task.func(**task.kwargs)
                except Exception as exc:  # noqa: BLE001 - best-effort background work must not break turns
                    logger.warning(
                        "background task failed", extra={"task_key": task.key}, exc_info=True
                    )
                    self._mark_job_failed(task.key, task.claim, str(exc))
                    with self._lock:
                        self._failed_total += 1
                else:
                    self._mark_job_succeeded(task.key, task.claim)
                    with self._lock:
                        self._completed_total += 1
            finally:
                self._release_job_claim(task.key, task.claim)
                with self._lock:
                    self._remove_job_claim(task.key, task.claim)
                    if self._active_workers > 0:
                        self._active_workers -= 1
                self._queue.task_done()

    def _mark_job_running(self, key: str, claim: BackgroundJobClaim | None) -> None:
        _invoke_job_backend_hook(
            self._job_deduper,
            key,
            claim,
            "mark_job_claim_running",
            "mark_job_running",
        )

    def _mark_job_succeeded(self, key: str, claim: BackgroundJobClaim | None) -> None:
        _invoke_job_backend_hook(
            self._job_deduper,
            key,
            claim,
            "mark_job_claim_succeeded",
            "mark_job_succeeded",
        )

    def _mark_job_failed(self, key: str, claim: BackgroundJobClaim | None, error: str) -> None:
        _invoke_job_backend_hook(
            self._job_deduper,
            key,
            claim,
            "mark_job_claim_failed",
            "mark_job_failed",
            error,
        )

    def _release_job_claim(self, key: str, claim: BackgroundJobClaim | None) -> None:
        _invoke_job_backend_hook(
            self._job_deduper,
            key,
            claim,
            "release_job_claim",
            "release_job_key",
        )

    def _remove_job_claim(self, key: str, claim: BackgroundJobClaim | None) -> None:
        current = self._job_claims.get(key)
        if claim is None or current == claim:
            self._job_claims.pop(key, None)


def _required_payload_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"background job payload field is required: {key}")
    return value.strip()


def _required_payload_namespace(payload: dict[str, Any]) -> tuple[str, ...]:
    value = payload.get("namespace")
    if isinstance(value, (list, tuple)):
        namespace = tuple(str(item).strip() for item in value if str(item).strip())
        if namespace:
            return namespace
    raise ValueError("background job payload field is required: namespace")


__all__ = [
    "BackgroundJobHandler",
    "BackgroundJobHandlerRegistry",
    "BackgroundTask",
    "BoundedBackgroundQueue",
    "DurableBackgroundWorker",
    "REGISTERED_BACKGROUND_JOB_KINDS",
    "register_default_background_job_handlers",
]
