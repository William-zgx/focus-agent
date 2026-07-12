from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from focus_agent.engine.runtime import AppRuntime
from focus_agent.harness.runtime import RunStatus
from focus_agent.services.chat import ChatService

from ...route_utils.branch_handoff_decisions import mark_branch_handoff_decision_outcome
from .replay_helpers import (
    _close_run_stream,
    _publish_run_event,
    _record_harness_turn_and_schedule,
    _safe_chat_values,
)

PublishRunEvent = Callable[..., Awaitable[None]]
SafeChatValues = Callable[..., dict[str, Any]]
SafeFailedThreadState = Callable[..., dict[str, Any] | None]
TaskOutcomeEventPayload = Callable[[Any], dict[str, Any]]
MarkHandoffOutcome = Callable[..., None]
RecordHarnessTurn = Callable[..., None]
CloseRunStream = Callable[..., Awaitable[None]]


class _RunEventPublisher:
    def __init__(
        self,
        *,
        runtime: AppRuntime,
        run_id: str,
        thread_id: str,
        default_source_node_name: str | None,
    ) -> None:
        self._runtime = runtime
        self._run_id = run_id
        self._thread_id = thread_id
        self._default_source_node_name = default_source_node_name
        self.sequence = 0

    async def __call__(
        self,
        event_name: str,
        source_node_name: str | None = None,
        **data: Any,
    ) -> None:
        self.sequence = await _publish_run_event(
            runtime=self._runtime,
            run_id=self._run_id,
            thread_id=self._thread_id,
            sequence=self.sequence,
            event_name=event_name,
            source_node_name=(
                self._default_source_node_name if source_node_name is None else source_node_name
            ),
            data=data,
        )


def _task_outcome_event_payload(task_outcome: Any) -> dict[str, Any]:
    return {"task_outcome": task_outcome} if task_outcome is not None else {}


def _is_cancel_cleanup_exception(exc: BaseException) -> bool:
    return isinstance(exc, ValueError) and "generator already executing" in str(exc)


def _safe_failed_thread_state(
    *,
    chat: ChatService,
    thread_id: str,
    user_id: str,
    context: Any,
    branch_meta: Any,
    trace_correlation: Any,
) -> dict[str, Any] | None:
    try:
        return chat._response_payload(
            thread_id=thread_id,
            user_id=user_id,
            context=context,
            branch_meta=branch_meta,
            interrupts=chat._safe_get_interrupts(thread_id),
            trace_correlation=trace_correlation,
        )
    except Exception:  # noqa: BLE001
        return None


async def _handle_cancelled_stream(
    *,
    runtime: AppRuntime,
    chat: ChatService,
    run_id: str,
    thread_id: str,
    user_id: str,
    context: Any,
    branch_meta: Any,
    trace_correlation: Any,
    publish: PublishRunEvent,
    handoff_decision: Any = None,
    handoff_message: str | None = None,
    mark_handoff: bool = False,
    safe_chat_values: SafeChatValues = _safe_chat_values,
    safe_failed_thread_state: SafeFailedThreadState = _safe_failed_thread_state,
    task_outcome_event_payload: TaskOutcomeEventPayload = _task_outcome_event_payload,
    mark_handoff_outcome: MarkHandoffOutcome = mark_branch_handoff_decision_outcome,
) -> None:
    await runtime.run_manager.set_status(run_id, RunStatus.INTERRUPTED)
    if mark_handoff:
        mark_handoff_outcome(
            runtime=runtime,
            decision=handoff_decision,
            run_status=RunStatus.INTERRUPTED.value,
            run_id=run_id,
            message=handoff_message,
            error="CancelledError",
        )
    record = runtime.run_manager.get(run_id)
    if record is not None and record.abort_event.is_set():
        return
    failed_values = safe_chat_values(chat=chat, thread_id=thread_id)
    failed_thread_state = safe_failed_thread_state(
        chat=chat,
        thread_id=thread_id,
        user_id=user_id,
        context=context,
        branch_meta=branch_meta,
        trace_correlation=trace_correlation,
    )
    await publish(
        "run.failed",
        error="CancelledError",
        message="Run was cancelled.",
        **({"thread_state": failed_thread_state} if failed_thread_state is not None else {}),
        **task_outcome_event_payload(failed_values.get("task_outcome")),
    )


async def _handle_stream_exception(
    *,
    runtime: AppRuntime,
    chat: ChatService,
    run_id: str,
    thread_id: str,
    user_id: str,
    context: Any,
    branch_meta: Any,
    trace_correlation: Any,
    publish: PublishRunEvent,
    exc: Exception,
    kind: str,
    final_payload: Any,
    initial_message_count: int,
    initial_llm_calls: int,
    started_at: Any,
    handoff_decision: Any = None,
    handoff_message: str | None = None,
    mark_handoff: bool = False,
    safe_chat_values: SafeChatValues = _safe_chat_values,
    safe_failed_thread_state: SafeFailedThreadState = _safe_failed_thread_state,
    task_outcome_event_payload: TaskOutcomeEventPayload = _task_outcome_event_payload,
    mark_handoff_outcome: MarkHandoffOutcome = mark_branch_handoff_decision_outcome,
    record_harness_turn: RecordHarnessTurn = _record_harness_turn_and_schedule,
) -> bool:
    record = runtime.run_manager.get(run_id)
    if record is not None and record.abort_event.is_set() and _is_cancel_cleanup_exception(exc):
        await runtime.run_manager.set_status(run_id, RunStatus.INTERRUPTED)
        if mark_handoff:
            mark_handoff_outcome(
                runtime=runtime,
                decision=handoff_decision,
                run_status=RunStatus.INTERRUPTED.value,
                run_id=run_id,
                message=handoff_message,
                error=str(exc),
            )
        return True
    if mark_handoff:
        mark_handoff_outcome(
            runtime=runtime,
            decision=handoff_decision,
            run_status=RunStatus.ERROR.value,
            run_id=run_id,
            message=handoff_message,
            error=str(exc),
        )
    await runtime.run_manager.set_status(run_id, RunStatus.ERROR, error=str(exc))
    failed_values = safe_chat_values(chat=chat, thread_id=thread_id)
    failed_thread_state = safe_failed_thread_state(
        chat=chat,
        thread_id=thread_id,
        user_id=user_id,
        context=context,
        branch_meta=branch_meta,
        trace_correlation=trace_correlation,
    )
    record_harness_turn(
        chat=chat,
        thread_id=thread_id,
        user_id=user_id,
        root_thread_id=context.root_thread_id,
        kind=kind,
        status="failed",
        final_values=failed_values,
        initial_message_count=initial_message_count,
        initial_llm_calls=initial_llm_calls,
        started_at=started_at,
        branch_meta=branch_meta,
        trace_correlation=trace_correlation,
        payload=final_payload,
        error=str(exc),
    )
    await publish(
        "run.failed",
        error=exc.__class__.__name__,
        message=str(exc),
        **({"thread_state": failed_thread_state} if failed_thread_state is not None else {}),
        **task_outcome_event_payload(failed_values.get("task_outcome")),
    )
    return False


async def _close_stream(
    *,
    runtime: AppRuntime,
    run_id: str,
    thread_id: str,
    sequence: int,
    close_run_stream: CloseRunStream = _close_run_stream,
) -> None:
    await close_run_stream(
        runtime=runtime,
        run_id=run_id,
        thread_id=thread_id,
        sequence=sequence,
    )
