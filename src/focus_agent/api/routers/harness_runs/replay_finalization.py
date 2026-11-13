from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from focus_agent.engine.runtime import AppRuntime
from focus_agent.harness.runtime import RunStatus
from focus_agent.services.chat import ChatService

from .replay_helpers import (
    _call_chat_hook,
    _context_for_turn,
    _record_harness_turn_and_schedule,
    _safe_chat_values,
)


@dataclass(frozen=True)
class _HarnessTurnFinalization:
    final_values: dict[str, Any]
    thread_state: dict[str, Any] | None


class _HarnessRunFinalizer:
    """Apply the same terminal bookkeeping to unary, streamed, and recovered turns."""

    def __init__(
        self,
        *,
        runtime: AppRuntime,
        chat: ChatService,
        run_id: str,
        thread_id: str,
        user_id: str,
        kind: str,
        context: Any,
        branch_meta: Any,
        trace_correlation: Any,
        payload: Any,
        initial_message_count: int,
        initial_llm_calls: int,
        started_at: Any,
        record_harness_turn: Any = _record_harness_turn_and_schedule,
    ) -> None:
        self.runtime = runtime
        self.chat = chat
        self.run_id = run_id
        self.thread_id = thread_id
        self.user_id = user_id
        self.kind = kind
        self.context = context
        self.branch_meta = branch_meta
        self.trace_correlation = trace_correlation
        self.payload = payload
        self.initial_message_count = initial_message_count
        self.initial_llm_calls = initial_llm_calls
        self.started_at = started_at
        self.record_harness_turn = record_harness_turn
        self._refreshed: tuple[Any, Any, dict[str, Any]] | None = None

    def refresh(self) -> tuple[Any, Any, dict[str, Any]]:
        if self._refreshed is None:
            self._refreshed = _context_for_turn(
                chat=self.chat,
                thread_id=self.thread_id,
                user_id=self.user_id,
                fallback_context=self.context,
                fallback_branch_meta=self.branch_meta,
            )
        return self._refreshed

    def _thread_state(
        self, *, context: Any, branch_meta: Any, values: dict[str, Any]
    ) -> dict[str, Any] | None:
        return _call_chat_hook(
            chat=self.chat,
            method="_response_payload",
            thread_id=self.thread_id,
            user_id=self.user_id,
            context=context,
            branch_meta=branch_meta,
            values=values,
            interrupts=_call_chat_hook(
                chat=self.chat,
                method="_safe_get_interrupts",
                thread_id=self.thread_id,
            )
            or [],
            trace_correlation=self.trace_correlation,
        )

    def _record(
        self,
        *,
        status: str,
        context: Any,
        branch_meta: Any,
        final_values: dict[str, Any],
        answer: str | None = None,
        error: str | None = None,
        schedule_side_effects: bool = True,
        payload: Any = None,
    ) -> None:
        self.record_harness_turn(
            chat=self.chat,
            thread_id=self.thread_id,
            user_id=self.user_id,
            root_thread_id=context.root_thread_id,
            kind=self.kind,
            status=status,
            final_values=final_values,
            initial_message_count=self.initial_message_count,
            initial_llm_calls=self.initial_llm_calls,
            started_at=self.started_at,
            branch_meta=branch_meta,
            trace_correlation=self.trace_correlation,
            payload=self.payload if payload is None else payload,
            answer=answer,
            error=error,
            schedule_side_effects=schedule_side_effects,
        )

    async def succeed(
        self,
        *,
        answer: str | None = None,
        fallback_answer: str | None = None,
        thread_state: dict[str, Any] | None = None,
        schedule_side_effects: bool = True,
        payload: Any = None,
    ) -> _HarnessTurnFinalization:
        latest_context, latest_branch_meta, final_values = self.refresh()
        if thread_state is None:
            thread_state = self._thread_state(
                context=latest_context,
                branch_meta=latest_branch_meta,
                values=final_values,
            )
        if answer is None and thread_state is not None:
            answer = thread_state.get("assistant_message")
        if answer is None:
            answer = fallback_answer
        self._record(
            status="succeeded",
            context=latest_context,
            branch_meta=latest_branch_meta,
            final_values=final_values,
            answer=answer,
            schedule_side_effects=schedule_side_effects,
            payload=payload,
        )
        await self.runtime.run_manager.set_status(self.run_id, RunStatus.SUCCESS)
        return _HarnessTurnFinalization(
            final_values=final_values,
            thread_state=thread_state,
        )

    async def fail(
        self,
        exc: Exception,
        *,
        run_status: RunStatus = RunStatus.ERROR,
        payload: Any = None,
    ) -> _HarnessTurnFinalization:
        await self.runtime.run_manager.set_status(self.run_id, run_status, error=str(exc))
        try:
            latest_context, latest_branch_meta, final_values = self.refresh()
        except Exception:  # noqa: BLE001 - preserve the original execution failure
            latest_context, latest_branch_meta = self.context, self.branch_meta
            try:
                final_values = _safe_chat_values(chat=self.chat, thread_id=self.thread_id)
            except Exception:  # noqa: BLE001
                final_values = {}
        try:
            thread_state = self._thread_state(
                context=latest_context,
                branch_meta=latest_branch_meta,
                values=final_values,
            )
        except Exception:  # noqa: BLE001
            thread_state = None
        self._record(
            status="timeout" if run_status is RunStatus.TIMEOUT else "failed",
            context=latest_context,
            branch_meta=latest_branch_meta,
            final_values=final_values,
            error=str(exc),
            payload=payload,
        )
        return _HarnessTurnFinalization(
            final_values=final_values,
            thread_state=thread_state,
        )


__all__ = ["_HarnessRunFinalizer", "_HarnessTurnFinalization"]
