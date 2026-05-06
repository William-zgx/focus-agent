from __future__ import annotations

import asyncio
import threading
from typing import Any

from ..core.branching import BranchMeta
from ..observability.tracing import TraceCorrelation
from .coordination import background_job_key
from .chat_trajectory import record_turn_trajectory_best_effort


class ChatTurnRecordingMixin:
    def _schedule_branch_name_refresh_after_first_turn(
        self,
        *,
        thread_id: str,
        user_id: str,
        branch_meta: BranchMeta | None,
        kind: str,
    ) -> None:
        branch_service = getattr(self.runtime, 'branch_service', None)
        if branch_service is None:
            return
        if kind != 'chat.turn':
            return

        def dispatch_background(func, **kwargs) -> None:
            submit_background = getattr(self, '_submit_background_work', None)
            if callable(submit_background):
                task_key = str(kwargs.pop('_background_task_key'))
                submit_background(key=task_key, func=func, **kwargs)
                return
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                threading.Thread(target=func, kwargs=kwargs, daemon=True).start()
                return
            loop.create_task(asyncio.to_thread(func, **kwargs))

        if branch_meta is None:
            refresh_title = getattr(branch_service, 'refresh_conversation_title_after_first_turn', None)
            if refresh_title is None:
                return
            task_key = background_job_key(kind="conversation_title", thread_id=thread_id)
            durable_enqueued = self._enqueue_durable_background_job(
                kind="conversation_title",
                key=task_key,
                payload={"root_thread_id": thread_id, "user_id": user_id},
                max_attempts=3,
                dedupe_policy="replace",
            )
            if durable_enqueued is not None:
                return
            dispatch_background(
                refresh_title,
                _background_task_key=task_key,
                root_thread_id=thread_id,
                user_id=user_id,
            )
            return
        refresh_branch = getattr(branch_service, 'refresh_branch_metadata_after_first_turn', None)
        if refresh_branch is None:
            refresh_branch = getattr(branch_service, 'refresh_branch_name_after_first_turn', None)
        if refresh_branch is None:
            return
        task_key = background_job_key(kind="branch_title", thread_id=thread_id)
        durable_enqueued = self._enqueue_durable_background_job(
            kind="branch_title",
            key=task_key,
            payload={"child_thread_id": thread_id, "user_id": user_id},
            max_attempts=3,
            dedupe_policy="replace",
        )
        if durable_enqueued is not None:
            return
        dispatch_background(
            refresh_branch,
            _background_task_key=task_key,
            child_thread_id=thread_id,
            user_id=user_id,
        )

    def _record_turn_trajectory_best_effort(
        self,
        *,
        thread_id: str,
        user_id: str,
        root_thread_id: str,
        kind: str,
        status: str,
        final_values: dict[str, Any],
        initial_message_count: int,
        initial_llm_calls: int,
        started_at,
        finished_at,
        branch_meta: BranchMeta | None,
        trace_correlation: TraceCorrelation | None = None,
        input_messages: list[Any] | None = None,
        answer: str | None = None,
        error: str | None = None,
    ) -> None:
        record_turn_trajectory_best_effort(
            recorder=getattr(self.runtime, 'trajectory_recorder', None),
            settings=self.runtime.settings,
            thread_id=thread_id,
            user_id=user_id,
            root_thread_id=root_thread_id,
            kind=kind,
            status=status,
            final_values=final_values,
            initial_message_count=initial_message_count,
            initial_llm_calls=initial_llm_calls,
            started_at=started_at,
            finished_at=finished_at,
            branch_meta=branch_meta,
            trace_correlation=trace_correlation,
            input_messages=input_messages,
            answer=answer,
            error=error,
        )
