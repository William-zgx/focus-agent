from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Request
from langchain.messages import HumanMessage

from focus_agent.engine.runtime import AppRuntime
from focus_agent.harness.runtime import RunStatus
from focus_agent.observability.tracing import build_invoke_config
from focus_agent.security.tokens import Principal
from focus_agent.services.chat import ChatService

from ...deps import get_app_runtime, get_chat_service, get_current_principal
from ...route_utils.branch_handoff_decisions import (
    mark_branch_handoff_decision_outcome,
    record_branch_handoff_decision_for_run,
)
from .replay_helpers import (
    _branch_action_intent_for_run,
    _capture_run_rollback_target,
    _context_for_turn,
    _create_run_record,
    _handle_branch_recommendation_for_run,
    _harness_run_response,
    _is_branch_handoff_auto_run,
    _prepare_run_payload,
    _record_harness_turn_and_schedule,
    _run_branch_action_turn_to_completion,
    _run_message_from_payload,
    _safe_chat_values,
    _trace_correlation,
    _turn_recording_baseline,
)
from .replay_models import HarnessRunRequest, HarnessRunResponse

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
    graph_payload, context, branch_meta, initial_values = _prepare_run_payload(
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
    skip_branch_recommendation: bool = False,
) -> HarnessRunResponse:
    await runtime.run_manager.set_status(run_record.run_id, RunStatus.RUNNING)
    initial_message_count, initial_llm_calls, started_at = _turn_recording_baseline(initial_values)
    input_messages = [HumanMessage(content=message)]
    trace_correlation = _trace_correlation(runtime=runtime, request_id=request_id)
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
        latest_context, latest_branch_meta, final_values = _context_for_turn(
            chat=chat,
            thread_id=thread_id,
            user_id=user_id,
            fallback_context=context,
            fallback_branch_meta=branch_meta,
        )
        _record_harness_turn_and_schedule(
            chat=chat,
            thread_id=thread_id,
            user_id=user_id,
            root_thread_id=latest_context.root_thread_id,
            kind="chat.turn",
            status="succeeded",
            final_values=final_values,
            initial_message_count=initial_message_count,
            initial_llm_calls=initial_llm_calls,
            started_at=started_at,
            branch_meta=latest_branch_meta,
            trace_correlation=trace_correlation,
            payload={"messages": input_messages},
            answer=str(result.get("message") or ""),
            schedule_side_effects=False,
        )
    except Exception as exc:  # noqa: BLE001
        await runtime.run_manager.set_status(run_record.run_id, RunStatus.ERROR, error=str(exc))
        _record_harness_turn_and_schedule(
            chat=chat,
            thread_id=thread_id,
            user_id=user_id,
            root_thread_id=context.root_thread_id,
            kind="chat.turn",
            status="failed",
            final_values=_safe_chat_values(chat=chat, thread_id=thread_id),
            initial_message_count=initial_message_count,
            initial_llm_calls=initial_llm_calls,
            started_at=started_at,
            branch_meta=branch_meta,
            trace_correlation=trace_correlation,
            payload={"messages": input_messages},
            error=str(exc),
        )
        raise
    await runtime.run_manager.set_status(run_record.run_id, RunStatus.SUCCESS)
    return _harness_run_response(
        runtime=runtime,
        run_id=run_record.run_id,
        fallback_record=run_record,
        thread_state=result["thread_state"],
    )


async def _execute_harness_run(
    *,
    runtime: AppRuntime,
    chat: ChatService,
    run_record: Any,
    thread_id: str,
    user_id: str,
    message: str,
    payload: dict[str, Any],
    request_id: str | None,
    context: Any,
    branch_meta: Any,
    initial_values: dict[str, Any],
    skip_branch_recommendation: bool = False,
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
    try:
        if not skip_branch_recommendation:
            branch_recommendation_result = _handle_branch_recommendation_for_run(
                chat=chat,
                thread_id=thread_id,
                user_id=user_id,
                message=message,
                request_id=request_id,
            )
            if branch_recommendation_result is not None:
                latest_context, latest_branch_meta, final_values = _context_for_turn(
                    chat=chat,
                    thread_id=thread_id,
                    user_id=user_id,
                    fallback_context=context,
                    fallback_branch_meta=branch_meta,
                )
                message_text = str(branch_recommendation_result.get("message") or "")
                _record_harness_turn_and_schedule(
                    chat=chat,
                    thread_id=thread_id,
                    user_id=user_id,
                    root_thread_id=latest_context.root_thread_id,
                    kind="chat.turn",
                    status="succeeded",
                    final_values=final_values,
                    initial_message_count=initial_message_count,
                    initial_llm_calls=initial_llm_calls,
                    started_at=started_at,
                    branch_meta=latest_branch_meta,
                    trace_correlation=trace_correlation,
                    payload={"messages": [HumanMessage(content=message)]},
                    answer=message_text or None,
                    schedule_side_effects=False,
                )
                await runtime.run_manager.set_status(run_record.run_id, RunStatus.SUCCESS)
                return _harness_run_response(
                    runtime=runtime,
                    run_id=run_record.run_id,
                    fallback_record=run_record,
                    thread_state=branch_recommendation_result["thread_state"],
                )
    except Exception as exc:  # noqa: BLE001
        mark_branch_handoff_decision_outcome(
            runtime=runtime,
            decision=handoff_decision,
            run_status=RunStatus.ERROR.value,
            run_id=run_record.run_id,
            message=message,
            error=str(exc),
        )
        await runtime.run_manager.set_status(run_record.run_id, RunStatus.ERROR, error=str(exc))
        _record_harness_turn_and_schedule(
            chat=chat,
            thread_id=thread_id,
            user_id=user_id,
            root_thread_id=context.root_thread_id,
            kind="chat.turn",
            status="failed",
            final_values=_safe_chat_values(chat=chat, thread_id=thread_id),
            initial_message_count=initial_message_count,
            initial_llm_calls=initial_llm_calls,
            started_at=started_at,
            branch_meta=branch_meta,
            trace_correlation=trace_correlation,
            payload={"messages": [HumanMessage(content=message)]},
            error=str(exc),
        )
        raise
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
        mark_branch_handoff_decision_outcome(
            runtime=runtime,
            decision=handoff_decision,
            run_status=RunStatus.ERROR.value,
            run_id=run_record.run_id,
            message=message,
            error=str(exc),
        )
        await runtime.run_manager.set_status(run_record.run_id, RunStatus.ERROR, error=str(exc))
        _record_harness_turn_and_schedule(
            chat=chat,
            thread_id=thread_id,
            user_id=user_id,
            root_thread_id=context.root_thread_id,
            kind="chat.turn",
            status="failed",
            final_values=_safe_chat_values(chat=chat, thread_id=thread_id),
            initial_message_count=initial_message_count,
            initial_llm_calls=initial_llm_calls,
            started_at=started_at,
            branch_meta=branch_meta,
            trace_correlation=trace_correlation,
            payload=payload,
            error=str(exc),
        )
        raise
    await runtime.run_manager.set_status(run_record.run_id, RunStatus.SUCCESS)
    mark_branch_handoff_decision_outcome(
        runtime=runtime,
        decision=handoff_decision,
        run_status=RunStatus.SUCCESS.value,
        run_id=run_record.run_id,
        message=message,
    )
    latest_context, latest_branch_meta, final_values = _context_for_turn(
        chat=chat,
        thread_id=thread_id,
        user_id=user_id,
        fallback_context=context,
        fallback_branch_meta=branch_meta,
    )
    thread_state = chat._response_payload(
        thread_id=thread_id,
        user_id=user_id,
        context=latest_context,
        branch_meta=latest_branch_meta,
        interrupts=chat._safe_get_interrupts(thread_id),
        trace_correlation=trace_correlation,
    )
    _record_harness_turn_and_schedule(
        chat=chat,
        thread_id=thread_id,
        user_id=user_id,
        root_thread_id=latest_context.root_thread_id,
        kind="chat.turn",
        status="succeeded",
        final_values=final_values,
        initial_message_count=initial_message_count,
        initial_llm_calls=initial_llm_calls,
        started_at=started_at,
        branch_meta=latest_branch_meta,
        trace_correlation=trace_correlation,
        payload=payload,
        answer=thread_state.get("assistant_message"),
    )
    return _harness_run_response(
        runtime=runtime,
        run_id=run_record.run_id,
        fallback_record=run_record,
        thread_state=thread_state,
    )
