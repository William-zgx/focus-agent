from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Request
from langchain.messages import HumanMessage
from langgraph.types import Command

from focus_agent.core.request_context import RequestContext
from focus_agent.engine.runtime import AppRuntime
from focus_agent.harness.runtime import RunConflictError, RunStatus
from focus_agent.harness.runtime.recovery import is_replay_safe_external_outcome
from focus_agent.harness.runtime.runs import (
    is_execution_terminal_run_status,
    is_replay_safe_run_status,
)
from focus_agent.observability.tracing import build_invoke_config
from focus_agent.security.tokens import Principal
from focus_agent.services.chat import ChatService

from ...deps import get_app_runtime, get_chat_service, get_current_principal
from ...route_helpers import run_sync_route_call
from ...route_utils.branch_handoff_decisions import (
    mark_branch_handoff_decision_outcome,
    record_branch_handoff_decision_for_run,
)
from .replay_finalization import _HarnessRunFinalizer
from .replay_helpers import (
    _COMMAND_RESUME_INPUT_KIND,
    _branch_action_intent_for_run,
    _branch_recommendation_timeout_seconds,
    _capture_run_rollback_target,
    _create_run_record,
    _get_persisted_run,
    _handle_branch_recommendation_for_run_async,
    _harness_run_response,
    _is_branch_handoff_auto_run,
    _message_text_from_graph_payload,
    _prepare_run_payload,
    _record_harness_turn_and_schedule,
    _run_branch_action_turn_to_completion,
    _run_message_from_payload,
    _safe_chat_values,
    _trace_correlation,
    _turn_recording_baseline,
)
from .replay_models import HarnessRunRequest, HarnessRunResponse
from .replay_streaming_lifecycle import _publish_recovered_stream_outcome

router = APIRouter(prefix="/v2", tags=["harness-runs"])


@router.post("/threads/{thread_id:path}/runs", response_model=HarnessRunResponse)
async def create_harness_run(
    thread_id: str,
    payload: HarnessRunRequest,
    request: Request,
    runtime: AppRuntime = Depends(get_app_runtime),
    chat: ChatService = Depends(get_chat_service),
    principal: Principal = Depends(get_current_principal),
) -> HarnessRunResponse:
    graph_payload, context, branch_meta, initial_values = await run_sync_route_call(
        _prepare_run_payload,
        thread_id=thread_id,
        user_id=principal.user_id,
        payload=payload,
        chat=chat,
    )
    rollback_target = _capture_run_rollback_target(runtime=runtime, thread_id=thread_id)
    skip_branch_recommendation = _is_branch_handoff_auto_run(payload)
    message = _run_message_from_payload(payload)
    is_branch_action = (not skip_branch_recommendation) and _branch_action_intent_for_run(
        chat=chat,
        initial_values=initial_values,
        branch_meta=branch_meta,
        message=message,
    )
    run_record = await _create_run_record(
        runtime=runtime,
        payload=payload,
        thread_id=thread_id,
        user_id=principal.user_id,
        graph_payload=graph_payload,
        rollback_target=rollback_target,
        rollback_partial=is_branch_action,
        rollback_unreverted_scopes=("branch_action",) if is_branch_action else (),
        context=context,
        branch_meta=branch_meta,
        request_id=getattr(request.state, "request_id", None),
        branch_action=is_branch_action,
        skip_branch_recommendation=skip_branch_recommendation,
    )
    if is_branch_action:
        return await _execute_branch_action_run(
            runtime=runtime,
            chat=chat,
            run_record=run_record,
            thread_id=thread_id,
            user_id=principal.user_id,
            message=message,
            request_id=getattr(request.state, "request_id", None),
            context=context,
            branch_meta=branch_meta,
            initial_values=initial_values,
        )
    return await _execute_harness_run(
        runtime=runtime,
        chat=chat,
        run_record=run_record,
        thread_id=thread_id,
        user_id=principal.user_id,
        message=message,
        payload=graph_payload,
        request_id=getattr(request.state, "request_id", None),
        context=context,
        branch_meta=branch_meta,
        initial_values=initial_values,
        skip_branch_recommendation=skip_branch_recommendation,
    )


async def _execute_branch_action_run(
    *,
    runtime: AppRuntime,
    chat: ChatService,
    run_record: Any,
    thread_id: str,
    user_id: str,
    message: str,
    request_id: str | None,
    context: Any,
    branch_meta: Any,
    initial_values: dict[str, Any],
) -> HarnessRunResponse:
    await runtime.run_manager.set_status(run_record.run_id, RunStatus.RUNNING)
    initial_message_count, initial_llm_calls, started_at = _turn_recording_baseline(initial_values)
    trace_correlation = _trace_correlation(runtime=runtime, request_id=request_id)
    finalizer = _HarnessRunFinalizer(
        runtime=runtime,
        chat=chat,
        run_id=run_record.run_id,
        thread_id=thread_id,
        user_id=user_id,
        kind="chat.turn",
        context=context,
        branch_meta=branch_meta,
        trace_correlation=trace_correlation,
        payload={"messages": [HumanMessage(content=message)]},
        initial_message_count=initial_message_count,
        initial_llm_calls=initial_llm_calls,
        started_at=started_at,
        record_harness_turn=_record_harness_turn_and_schedule,
    )
    try:
        result = await _run_branch_action_turn_to_completion(
            chat=chat,
            thread_id=thread_id,
            user_id=user_id,
            message=message,
            request_id=request_id,
        )
        if result is None:
            raise RuntimeError("Branch action intent disappeared before execution.")
    except Exception as exc:  # noqa: BLE001
        await finalizer.fail(exc)
        raise
    finalization = await finalizer.succeed(
        answer=str(result.get("message") or ""),
        thread_state=result["thread_state"],
        schedule_side_effects=False,
    )
    return _harness_run_response(
        runtime=runtime,
        run_id=run_record.run_id,
        fallback_record=run_record,
        thread_state=finalization.thread_state,
    )


async def _execute_harness_run(
    *,
    runtime: AppRuntime,
    chat: ChatService,
    run_record: Any,
    thread_id: str,
    user_id: str,
    message: str,
    payload: Any,
    request_id: str | None,
    context: Any,
    branch_meta: Any,
    initial_values: dict[str, Any],
    skip_branch_recommendation: bool = False,
    kind: str = "chat.turn",
    config: dict[str, Any] | None = None,
) -> HarnessRunResponse:
    await runtime.run_manager.set_status(run_record.run_id, RunStatus.RUNNING)
    initial_message_count, initial_llm_calls, started_at = _turn_recording_baseline(initial_values)
    trace_correlation = _trace_correlation(runtime=runtime, request_id=request_id)
    handoff_decision = (
        record_branch_handoff_decision_for_run(
            runtime=runtime,
            thread_id=thread_id,
            user_id=user_id,
            message=message,
            root_thread_id=context.root_thread_id,
            request_id=request_id,
            trace_id=getattr(trace_correlation, "trace_id", None)
            if trace_correlation is not None
            else None,
            run_id=run_record.run_id,
            run_status=RunStatus.RUNNING.value,
        )
        if skip_branch_recommendation
        else None
    )
    finalizer = _HarnessRunFinalizer(
        runtime=runtime,
        chat=chat,
        run_id=run_record.run_id,
        thread_id=thread_id,
        user_id=user_id,
        kind=kind,
        context=context,
        branch_meta=branch_meta,
        trace_correlation=trace_correlation,
        payload=payload,
        initial_message_count=initial_message_count,
        initial_llm_calls=initial_llm_calls,
        started_at=started_at,
        record_harness_turn=_record_harness_turn_and_schedule,
    )
    turn_payload = {"messages": [HumanMessage(content=message)]}
    succeeded = False

    async def record_failure(exc: Exception, failed_payload: Any) -> None:
        mark_branch_handoff_decision_outcome(
            runtime=runtime,
            decision=handoff_decision,
            run_status=RunStatus.ERROR.value,
            run_id=run_record.run_id,
            message=message,
            error=str(exc),
        )
        await finalizer.fail(exc, payload=failed_payload)

    try:
        if chat is not None and not skip_branch_recommendation:
            branch_recommendation_result = await _handle_branch_recommendation_for_run_async(
                chat=chat,
                thread_id=thread_id,
                user_id=user_id,
                message=message,
                request_id=request_id,
                timeout_seconds=_branch_recommendation_timeout_seconds(runtime.settings),
            )
            if branch_recommendation_result is not None:
                message_text = str(branch_recommendation_result.get("message") or "")
                finalization = await finalizer.succeed(
                    answer=message_text or None,
                    thread_state=branch_recommendation_result["thread_state"],
                    schedule_side_effects=False,
                    payload=turn_payload,
                )
                succeeded = True
                return _harness_run_response(
                    runtime=runtime,
                    run_id=run_record.run_id,
                    fallback_record=run_record,
                    thread_state=finalization.thread_state,
                )
    except Exception as exc:  # noqa: BLE001
        if succeeded:
            raise
        await record_failure(exc, turn_payload)
        raise
    if config is None:
        config = build_invoke_config(
            settings=getattr(runtime, "settings", {}),
            thread_id=thread_id,
            user_id=user_id,
            root_thread_id=context.root_thread_id,
            branch_meta=branch_meta,
            trace_correlation=trace_correlation,
            run_name="focus_agent_harness_run",
        )
    try:
        await asyncio.to_thread(
            runtime.harness.invoke,
            payload,
            config=config,
            context=context,
            version="v2",
        )
    except Exception as exc:  # noqa: BLE001
        await record_failure(exc, payload)
        raise
    try:
        mark_branch_handoff_decision_outcome(
            runtime=runtime,
            decision=handoff_decision,
            run_status=RunStatus.SUCCESS.value,
            run_id=run_record.run_id,
            message=message,
        )
        finalization = await finalizer.succeed()
        return _harness_run_response(
            runtime=runtime,
            run_id=run_record.run_id,
            fallback_record=run_record,
            thread_state=finalization.thread_state,
        )
    except Exception as exc:  # noqa: BLE001
        await record_failure(exc, payload)
        raise


def _run_on_manager_loop(*, runtime: AppRuntime, awaitable: Any) -> Any:
    loop = getattr(runtime.run_manager, "_loop", None)
    if loop is not None and loop.is_running():
        return asyncio.run_coroutine_threadsafe(awaitable, loop).result()
    return asyncio.run(awaitable)


def _ack_terminal_persisted_run(*, runtime: AppRuntime, run_id: str) -> None:
    persisted = _run_on_manager_loop(
        runtime=runtime,
        awaitable=_get_persisted_run(runtime, run_id),
    )
    if persisted is None:
        raise KeyError(f"unknown hydrated harness run: {run_id}")
    status = str(persisted.get("status") or "")
    if is_execution_terminal_run_status(status):
        return
    if status == RunStatus.RECONCILIATION_REQUIRED.value:
        raise RuntimeError(f"harness run requires reconciliation before execution: {run_id}")
    raise RuntimeError(f"harness run is not hydrated and cannot execute safely: {run_id}")


def execute_harness_run_job(
    *, runtime: AppRuntime, chat: ChatService, payload: dict[str, Any]
) -> None:
    """Execute one hydrated harness run without replaying closed work."""
    run_id = str(payload.get("run_id") or "")
    if not run_id:
        raise ValueError("harness_run payload requires run_id")
    record = runtime.run_manager.get(run_id)
    if record is None:
        _ack_terminal_persisted_run(runtime=runtime, run_id=run_id)
        return
    if record.status == RunStatus.RECONCILIATION_REQUIRED:
        raise RuntimeError(f"harness run requires reconciliation before execution: {run_id}")
    if is_execution_terminal_run_status(record.status):
        return
    if record.status == RunStatus.RUNNING and not is_replay_safe_external_outcome(
        record.metadata.get("external_outcome")
    ):
        raise RuntimeError(f"harness run outcome requires reconciliation: {run_id}")
    if not is_replay_safe_run_status(record.status):
        raise RuntimeError(
            f"harness run cannot execute from status {record.status.value}: {run_id}"
        )
    if record.task is not None and not record.task.done():
        raise RunConflictError(f"harness run is already active: {run_id}")
    if record.task is not None and record.status == RunStatus.RUNNING and record.task.done():
        raise RuntimeError(f"harness run outcome requires reconciliation: {run_id}")

    persisted_payload = record.kwargs.get("input")
    input_kind = record.kwargs.get("input_kind")
    if input_kind == _COMMAND_RESUME_INPUT_KIND:
        if not isinstance(persisted_payload, dict) or "resume" not in persisted_payload:
            raise ValueError(f"harness run has no persisted resume payload: {run_id}")
        graph_payload = Command(resume=persisted_payload["resume"])
    elif input_kind in {None, "messages"}:
        graph_payload = persisted_payload
    else:
        raise ValueError(f"harness run has unsupported input kind {input_kind!r}: {run_id}")
    if graph_payload is None:
        raise ValueError(f"harness run has no persisted graph payload: {run_id}")

    initial_values = (
        _safe_chat_values(chat=chat, thread_id=record.thread_id) if chat is not None else {}
    )
    original_config = record.kwargs.get("config")
    if isinstance(original_config, dict) and original_config:
        config = original_config
    else:
        config = build_invoke_config(
            settings=runtime.settings,
            thread_id=record.thread_id,
            user_id=record.user_id,
            root_thread_id=record.thread_id,
            run_name="focus_agent_harness_recovery",
        )
    original_context = record.kwargs.get("context")
    if isinstance(original_context, dict):
        context = RequestContext(**original_context)
    else:
        context = RequestContext(user_id=record.user_id, root_thread_id=record.thread_id)
    kind = str(
        record.kwargs.get("kind")
        or ("chat.resume" if input_kind == _COMMAND_RESUME_INPUT_KIND else "chat.turn")
    )
    skip_branch_recommendation = (
        bool(record.kwargs.get("skip_branch_recommendation")) or kind == "chat.resume"
    )

    def _complete_recovered_stream(response: Any = None, error: Exception | None = None) -> None:
        if not record.kwargs.get("stream"):
            return
        final_values = _safe_chat_values(chat=chat, thread_id=record.thread_id) if chat else {}
        _run_on_manager_loop(
            runtime=runtime,
            awaitable=_publish_recovered_stream_outcome(
                runtime=runtime,
                run_id=run_id,
                thread_id=record.thread_id,
                response=response,
                error=error,
                final_values=final_values,
            ),
        )

    try:
        if record.kwargs.get("branch_action"):
            if chat is None:
                raise RuntimeError(f"branch-action harness run requires chat service: {run_id}")
            response = _run_on_manager_loop(
                runtime=runtime,
                awaitable=_execute_branch_action_run(
                    runtime=runtime,
                    chat=chat,
                    run_record=record,
                    thread_id=record.thread_id,
                    user_id=record.user_id,
                    message=_message_text_from_graph_payload(graph_payload),
                    request_id=record.metadata.get("request_id"),
                    context=context,
                    branch_meta=record.kwargs.get("branch_meta"),
                    initial_values=initial_values,
                ),
            )
        else:
            response = _run_on_manager_loop(
                runtime=runtime,
                awaitable=_execute_harness_run(
                    runtime=runtime,
                    chat=chat,
                    run_record=record,
                    thread_id=record.thread_id,
                    user_id=record.user_id,
                    message=_message_text_from_graph_payload(graph_payload),
                    payload=graph_payload,
                    request_id=record.metadata.get("request_id"),
                    context=context,
                    branch_meta=record.kwargs.get("branch_meta"),
                    initial_values=initial_values,
                    skip_branch_recommendation=skip_branch_recommendation,
                    kind=kind,
                    config=config,
                ),
            )
    except Exception as exc:
        _complete_recovered_stream(error=exc)
        raise
    _complete_recovered_stream(response=response)
