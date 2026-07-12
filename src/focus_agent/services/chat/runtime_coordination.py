from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from ...core.repo_call import has_repo_method
from ...observability.trajectory import utc_now
from ..coordination import BackgroundJobSpec, background_job_key

if TYPE_CHECKING:
    from ..thread_turn_lease import ThreadTurnLeaseManager

logger = logging.getLogger("focus_agent.chat")


class ChatRuntimeCoordinationMixin:
    def _thread_turn_lease(self, *, thread_id: str) -> ThreadTurnLeaseManager:
        from ..thread_turn_lease import ThreadTurnLeaseManager

        return ThreadTurnLeaseManager(
            backend=self._coordination_backend.thread_turns,
            thread_id=thread_id,
            ttl_seconds=self._thread_turn_lock_ttl_seconds(),
            heartbeat_interval_seconds=self._thread_turn_lock_heartbeat_seconds(),
        )

    def _acquire_thread_turn(self, *, thread_id: str) -> None:
        lease = self._thread_turn_lease(thread_id=thread_id)
        lease.acquire()
        with self._active_turns_lock:
            self._active_turn_leases[thread_id] = lease

    def _heartbeat_thread_turn(self, *, thread_id: str) -> bool:
        with self._active_turns_lock:
            lease = self._active_turn_leases.get(thread_id)
        if lease is None:
            return False
        return lease.heartbeat_once()

    def _release_thread_turn(self, *, thread_id: str) -> None:
        with self._active_turns_lock:
            lease = self._active_turn_leases.pop(thread_id, None)
        if lease is not None:
            lease.close()

    def _thread_turn_lock_ttl_seconds(self) -> float:
        return max(
            float(
                getattr(self.runtime.settings, "runtime_thread_lock_ttl_seconds", 300.0) or 300.0
            ),
            1.0,
        )

    def _thread_turn_lock_heartbeat_seconds(self) -> float:
        ttl_seconds = self._thread_turn_lock_ttl_seconds()
        configured_seconds = float(
            getattr(self.runtime.settings, "runtime_thread_lock_heartbeat_seconds", 30.0) or 30.0
        )
        return max(min(ttl_seconds / 3.0, configured_seconds), 0.001)

    def _submit_background_work(
        self, *, key: str, func, delay_seconds: float = 0.0, **kwargs: Any
    ) -> bool:
        if self._background_work is None:
            from ..background_work import BoundedBackgroundQueue

            settings = self.runtime.settings
            self._background_work = BoundedBackgroundQueue(
                name="chat",
                max_concurrency=getattr(settings, "background_worker_max_concurrency", 2),
                max_size=getattr(settings, "background_queue_max_size", 1000),
                job_deduper=self._coordination_backend.job_deduper,
            )
        return self._background_work.submit(
            key=key,
            func=func,
            delay_seconds=delay_seconds,
            **kwargs,
        )

    def _release_background_job_key(self, key: str) -> None:
        if has_repo_method(self._background_work, "release_job_key"):
            self._background_work.release_job_key(key)
            return
        self._coordination_backend.job_deduper.release_job_key(key)

    def _durable_background_execution_enabled(self) -> bool:
        return (
            str(getattr(self.runtime.settings, "background_job_execution", "best_effort"))
            .strip()
            .lower()
            == "durable"
        )

    def _enqueue_durable_background_job(
        self,
        *,
        kind: str,
        key: str,
        payload: dict[str, Any],
        delay_seconds: float = 0.0,
        max_attempts: int = 3,
        dedupe_policy: str = "replace",
    ) -> bool | None:
        if not self._durable_background_execution_enabled():
            return None
        if not has_repo_method(self._coordination_backend.job_deduper, "enqueue_job"):
            return None
        try:
            return bool(
                self._coordination_backend.job_deduper.enqueue_job(
                    BackgroundJobSpec(
                        kind=kind,
                        key=key,
                        payload=payload,
                        run_at=utc_now() + timedelta(seconds=max(float(delay_seconds or 0.0), 0.0)),
                        max_attempts=max_attempts,
                        dedupe_policy=dedupe_policy,
                    )
                )
            )
        except Exception:  # noqa: BLE001 - post-turn scheduling must not fail the completed turn
            logger.warning(
                "failed to enqueue durable background job; falling back to best-effort scheduling",
                extra={"job_key": key, "job_kind": kind},
                exc_info=True,
            )
            return None

    def _schedule_post_turn_branch_decision(
        self,
        *,
        thread_id: str,
        user_id: str,
        root_thread_id: str,
        request_id: str | None,
        trace_id: str | None,
    ) -> None:
        branch_decision_service = getattr(self.runtime, "branch_decision_service", None)
        if branch_decision_service is None:
            return
        config = getattr(branch_decision_service, "config", lambda: None)()
        if config is None or not bool(getattr(config, "enabled", False)):
            return
        job_key = background_job_key(kind="branch_decision_evaluate", thread_id=thread_id)
        payload = {
            "thread_id": thread_id,
            "user_id": user_id,
            "root_thread_id": root_thread_id,
            "request_id": request_id,
            "trace_id": trace_id,
        }
        durable_enqueued = self._enqueue_durable_background_job(
            kind="branch_decision_evaluate",
            key=job_key,
            payload=payload,
            delay_seconds=0.05,
            max_attempts=3,
            dedupe_policy="replace",
        )
        if durable_enqueued is not None:
            return
        handler = getattr(branch_decision_service, "evaluate_thread_turn", None)
        if not callable(handler):
            return
        self._submit_background_work(
            key=job_key,
            func=handler,
            delay_seconds=0.05,
            **payload,
        )
