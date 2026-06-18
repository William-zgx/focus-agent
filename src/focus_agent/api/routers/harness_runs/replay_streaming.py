from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from langchain.messages import HumanMessage

from focus_agent.core.tool_protocol import (
    looks_like_textual_tool_call_artifact,
    safe_visible_text_transition,
)
from focus_agent.engine.runtime import AppRuntime
from focus_agent.harness.runtime import RunStatus
from focus_agent.observability.tracing import build_invoke_config
from focus_agent.security.tokens import Principal
from focus_agent.services.chat import ChatService
from focus_agent.transport.stream_events import (
    STREAM_VISIBILITY_VISIBLE,
    extract_reasoning_delta,
    extract_tool_call_chunks,
    extract_tool_requests_from_updates,
    extract_tool_results_from_updates,
    extract_visible_text_candidate_delta,
    looks_like_stream_visible_text_artifact,
    map_custom_payload_to_event,
    safe_stream_visible_text_transition,
    sanitize_stream_metadata,
    sanitize_stream_visible_text,
    stream_visibility_phase_from_metadata,
)

from ...deps import get_app_runtime, get_chat_service, get_current_principal
from ...route_utils.branch_handoff_decisions import (
    mark_branch_handoff_decision_outcome,
    record_branch_handoff_decision_for_run,
)
from .replay_helpers import (
    _branch_action_intent_for_run,
    _branch_recommendation_timeout_seconds,
    _canonical_custom_event,
    _capture_run_rollback_target,
    _close_run_stream,
    _context_for_turn,
    _create_run_record,
    _handle_branch_recommendation_for_run_async,
    _is_branch_handoff_auto_run,
    _is_tool_result_fallback_visible_delta,
    _message_text_from_graph_payload,
    _prepare_resume_payload,
    _prepare_run_payload,
    _publish_run_event,
    _record_harness_turn_and_schedule,
    _run_branch_action_turn_to_completion,
    _run_event_streaming_response,
    _run_message_from_payload,
    _safe_chat_values,
    _safe_completed_visible_text,
    _source_node,
    _tool_result_is_error,
    _trace_correlation,
    _turn_recording_baseline,
)
from .replay_models import HarnessResumeRequest, HarnessRunRequest

router = APIRouter(prefix="/v2", tags=["harness-runs"])

_INTERNAL_MESSAGE_STREAM_NODES = frozenset({"plan", "reflect"})


def _task_outcome_event_payload(task_outcome: Any) -> dict[str, Any]:
    return {"task_outcome": task_outcome} if task_outcome is not None else {}


def _is_cancel_cleanup_exception(exc: BaseException) -> bool:
    return isinstance(exc, ValueError) and "generator already executing" in str(exc)


@router.post("/threads/{thread_id:path}/runs/stream")
async def stream_harness_run(
    thread_id: str,
    payload: HarnessRunRequest,
    request: Request,
    runtime: AppRuntime = Depends(get_app_runtime),
    chat: ChatService = Depends(get_chat_service),
    principal: Principal = Depends(get_current_principal),
) -> StreamingResponse:
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
        producer = asyncio.create_task(
            _produce_branch_action_run_stream(
                runtime=runtime,
                chat=chat,
                run_id=run_record.run_id,
                thread_id=thread_id,
                user_id=principal.user_id,
                message=message,
                request_id=getattr(request.state, "request_id", None),
                context=context,
                branch_meta=branch_meta,
                initial_values=initial_values,
                kind="chat.turn",
            )
        )
    else:
        producer = asyncio.create_task(
            _produce_run_stream(
                runtime=runtime,
                chat=chat,
                run_id=run_record.run_id,
                thread_id=thread_id,
                user_id=principal.user_id,
                payload=graph_payload,
                context=context,
                branch_meta=branch_meta,
                initial_values=initial_values,
                request_id=getattr(request.state, "request_id", None),
                message=message,
                kind="chat.turn",
                skip_branch_recommendation=skip_branch_recommendation,
            )
        )
    await runtime.run_manager.attach_task(run_record.run_id, producer)

    return _run_event_streaming_response(
        runtime=runtime,
        run_id=run_record.run_id,
        thread_id=thread_id,
        request=request,
        cancel_on_disconnect=True,
    )


@router.post("/threads/{thread_id:path}/runs/resume/stream")
async def stream_harness_resume(
    thread_id: str,
    payload: HarnessResumeRequest,
    request: Request,
    runtime: AppRuntime = Depends(get_app_runtime),
    chat: ChatService = Depends(get_chat_service),
    principal: Principal = Depends(get_current_principal),
) -> StreamingResponse:
    command, context, branch_meta, initial_values = _prepare_resume_payload(
        thread_id=thread_id,
        user_id=principal.user_id,
        payload=payload,
        chat=chat,
    )
    rollback_target = _capture_run_rollback_target(runtime=runtime, thread_id=thread_id)
    run_record = await _create_run_record(
        runtime=runtime,
        payload=payload,
        thread_id=thread_id,
        user_id=principal.user_id,
        graph_payload=command,
        rollback_target=rollback_target,
    )
    producer = asyncio.create_task(
        _produce_run_stream(
            runtime=runtime,
            chat=chat,
            run_id=run_record.run_id,
            thread_id=thread_id,
            user_id=principal.user_id,
            payload=command,
            context=context,
            branch_meta=branch_meta,
            initial_values=initial_values,
            request_id=getattr(request.state, "request_id", None),
            kind="chat.resume",
            skip_branch_recommendation=True,
        )
    )
    await runtime.run_manager.attach_task(run_record.run_id, producer)

    return _run_event_streaming_response(
        runtime=runtime,
        run_id=run_record.run_id,
        thread_id=thread_id,
        request=request,
        cancel_on_disconnect=True,
    )


async def _produce_run_stream(
    *,
    runtime: AppRuntime,
    chat: ChatService,
    run_id: str,
    thread_id: str,
    user_id: str,
    payload: Any,
    context: Any,
    branch_meta: Any,
    initial_values: dict[str, Any],
    request_id: str | None,
    message: str | None = None,
    kind: str = "chat.turn",
    skip_branch_recommendation: bool = False,
) -> None:
    sequence = 0
    visible_text_buffer = ""
    visible_text_pending = ""
    reasoning_buffer = ""
    reasoning_text_pending = ""
    cancelled = False
    initial_message_count, initial_llm_calls, started_at = _turn_recording_baseline(initial_values)
    trace_correlation = _trace_correlation(runtime=runtime, request_id=request_id)
    handoff_decision = (
        record_branch_handoff_decision_for_run(
            runtime=runtime,
            thread_id=thread_id,
            user_id=user_id,
            message=message or _message_text_from_graph_payload(payload),
            root_thread_id=context.root_thread_id,
            request_id=request_id,
            trace_id=getattr(trace_correlation, "trace_id", None)
            if trace_correlation is not None
            else None,
            run_id=run_id,
            run_status=RunStatus.RUNNING.value,
        )
        if skip_branch_recommendation
        else None
    )
    config = build_invoke_config(
        settings=runtime.settings,
        thread_id=thread_id,
        user_id=user_id,
        root_thread_id=context.root_thread_id,
        branch_meta=branch_meta,
        trace_correlation=trace_correlation,
        run_name="focus_agent_harness_stream",
    )

    async def publish(event_name: str, source_node_name: str | None = None, **data: Any) -> None:
        nonlocal sequence
        sequence = await _publish_run_event(
            runtime=runtime,
            run_id=run_id,
            thread_id=thread_id,
            sequence=sequence,
            event_name=event_name,
            source_node_name=source_node_name,
            data=data,
        )

    try:
        await runtime.run_manager.set_status(run_id, RunStatus.RUNNING)
        await publish("run.metadata")
        await publish("run.status", phase="running")
        turn_message = str(message or _message_text_from_graph_payload(payload))
        if turn_message and not skip_branch_recommendation:
            branch_recommendation_result = await _handle_branch_recommendation_for_run_async(
                chat=chat,
                thread_id=thread_id,
                user_id=user_id,
                message=turn_message,
                request_id=request_id,
                timeout_seconds=_branch_recommendation_timeout_seconds(runtime.settings),
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
                if message_text and not looks_like_textual_tool_call_artifact(message_text):
                    await publish(
                        "message.completed",
                        content=message_text,
                        source="branch_recommendation",
                    )
                _record_harness_turn_and_schedule(
                    chat=chat,
                    thread_id=thread_id,
                    user_id=user_id,
                    root_thread_id=latest_context.root_thread_id,
                    kind=kind,
                    status="succeeded",
                    final_values=final_values,
                    initial_message_count=initial_message_count,
                    initial_llm_calls=initial_llm_calls,
                    started_at=started_at,
                    branch_meta=latest_branch_meta,
                    trace_correlation=trace_correlation,
                    payload={"messages": [HumanMessage(content=turn_message)]},
                    answer=message_text or None,
                    schedule_side_effects=False,
                )
                await runtime.run_manager.set_status(run_id, RunStatus.SUCCESS)
                await publish(
                    "run.completed",
                    status="succeeded",
                    thread_state=branch_recommendation_result.get("thread_state"),
                    branch_action=branch_recommendation_result.get("branch_action"),
                    branch_decision=branch_recommendation_result.get("branch_decision"),
                )
                return
        async for chunk in runtime.harness.stream_chunks(
            checkpointer=getattr(runtime, "checkpointer", None),
            settings=runtime.settings,
            payload=payload,
            config=config,
            context=context,
        ):
            record = runtime.run_manager.get(run_id)
            if record is not None and record.abort_event.is_set():
                cancelled = True
                await publish("run.status", phase="cancelled")
                break
            if chunk is None:
                await publish("heartbeat")
                continue
            chunk_type = chunk.get("type")
            data = chunk.get("data")
            namespace = list(chunk.get("ns") or ())
            chunk_metadata = sanitize_stream_metadata(chunk.get("metadata"))
            source_node = _source_node(chunk_metadata, namespace)
            if chunk_type == "messages":
                message_chunk, metadata = data
                safe_metadata = sanitize_stream_metadata(metadata)
                stream_phase = stream_visibility_phase_from_metadata(metadata)
                source_node = _source_node(safe_metadata, namespace)
                is_internal = source_node in _INTERNAL_MESSAGE_STREAM_NODES
                tool_chunks = extract_tool_call_chunks(message_chunk)
                visible_delta = extract_visible_text_candidate_delta(message_chunk)
                safe_visible_delta = sanitize_stream_visible_text(visible_delta)
                hide_visible_delta = (
                    stream_phase != STREAM_VISIBILITY_VISIBLE
                    or is_internal
                    or bool(tool_chunks)
                    or _is_tool_result_fallback_visible_delta(visible_delta)
                    or (
                        looks_like_stream_visible_text_artifact(visible_delta)
                        and not safe_visible_delta
                    )
                )
                if hide_visible_delta:
                    visible_text_pending = ""
                if visible_delta and not hide_visible_delta:
                    next_visible_text, visible_text_pending = safe_stream_visible_text_transition(
                        visible_text_buffer,
                        visible_delta,
                        pending_text=visible_text_pending,
                    )
                    if next_visible_text.startswith(visible_text_buffer):
                        publish_delta = next_visible_text[len(visible_text_buffer) :]
                    else:
                        publish_delta = next_visible_text
                    visible_text_buffer = next_visible_text
                    if publish_delta:
                        await publish(
                            "message.delta",
                            source_node,
                            delta=publish_delta,
                            message_id=str(getattr(message_chunk, "id", None) or run_id),
                            metadata=safe_metadata,
                            namespace=namespace,
                        )
                reasoning_delta = extract_reasoning_delta(message_chunk)
                if reasoning_delta and not is_internal:
                    next_reasoning_text, reasoning_text_pending = safe_visible_text_transition(
                        reasoning_buffer,
                        reasoning_delta,
                        pending_text=reasoning_text_pending,
                    )
                    if next_reasoning_text.startswith(reasoning_buffer):
                        publish_reasoning_delta = next_reasoning_text[len(reasoning_buffer) :]
                    else:
                        publish_reasoning_delta = next_reasoning_text
                    reasoning_buffer = next_reasoning_text
                    if publish_reasoning_delta:
                        await publish(
                            "reasoning.delta",
                            source_node,
                            delta=publish_reasoning_delta,
                            message_id=str(getattr(message_chunk, "id", None) or run_id),
                            metadata=safe_metadata,
                            namespace=namespace,
                        )
                for tool_chunk in tool_chunks:
                    await publish(
                        "tool.call.delta",
                        source_node,
                        **tool_chunk,
                        tool_call_id=tool_chunk.get("tool_call_id") or tool_chunk.get("id"),
                        metadata=safe_metadata,
                        namespace=namespace,
                    )
                continue
            if chunk_type == "custom":
                mapped_event, mapped_payload = map_custom_payload_to_event(data)
                canonical = _canonical_custom_event(mapped_event, mapped_payload)
                await publish(canonical, source_node, **mapped_payload, namespace=namespace)
                continue
            if chunk_type == "updates":
                for item in extract_tool_requests_from_updates(data):
                    await publish("tool.requested", item.get("node"), **item, namespace=namespace)
                for item in extract_tool_results_from_updates(data):
                    event = "tool.error" if _tool_result_is_error(item) else "tool.result"
                    await publish(event, item.get("node"), **item, namespace=namespace)
                await publish(
                    "state.update",
                    source_node,
                    data=data,
                    metadata=chunk_metadata,
                    namespace=namespace,
                )
                continue
            if chunk_type == "tasks":
                task_payload = data if isinstance(data, dict) else {"value": data}
                await publish(
                    "task.update",
                    source_node,
                    **task_payload,
                    metadata=chunk_metadata,
                    namespace=namespace,
                )

        if cancelled:
            await runtime.run_manager.set_status(run_id, RunStatus.INTERRUPTED)
            mark_branch_handoff_decision_outcome(
                runtime=runtime,
                decision=handoff_decision,
                run_status=RunStatus.INTERRUPTED.value,
                run_id=run_id,
                message=turn_message,
            )
            return

        latest_context, latest_branch_meta, final_values = chat._context_for_thread(
            thread_id=thread_id,
            user_id=user_id,
        )
        final_task_outcome = final_values.get("task_outcome")
        final_messages = list(final_values.get("messages", []) or [])
        appended_messages = (
            final_messages[initial_message_count:]
            if len(final_messages) >= initial_message_count
            else final_messages
        )
        graph_final_text = chat._latest_final_ai_text(appended_messages)
        if graph_final_text:
            graph_final_text = _safe_completed_visible_text(graph_final_text)
        if graph_final_text:
            final_visible_text = graph_final_text
            final_visible_source = "graph_state"
        else:
            final_visible_text = _safe_completed_visible_text(visible_text_buffer)
            final_visible_source = "stream_buffer"
        if final_visible_text:
            await publish(
                "message.completed",
                content=final_visible_text,
                source=final_visible_source,
                **_task_outcome_event_payload(final_task_outcome),
            )
        if reasoning_buffer:
            await publish("reasoning.delta", delta="", completed=True, content=reasoning_buffer)
        await runtime.run_manager.set_status(run_id, RunStatus.SUCCESS)
        mark_branch_handoff_decision_outcome(
            runtime=runtime,
            decision=handoff_decision,
            run_status=RunStatus.SUCCESS.value,
            run_id=run_id,
            message=turn_message,
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
            kind=kind,
            status="succeeded",
            final_values=final_values,
            initial_message_count=initial_message_count,
            initial_llm_calls=initial_llm_calls,
            started_at=started_at,
            branch_meta=latest_branch_meta,
            trace_correlation=trace_correlation,
            payload=payload,
            answer=thread_state.get("assistant_message") or final_visible_text or None,
        )
        await publish(
            "run.completed",
            status="succeeded",
            thread_state=thread_state,
            **_task_outcome_event_payload(final_task_outcome),
        )
    except asyncio.CancelledError:
        await runtime.run_manager.set_status(run_id, RunStatus.INTERRUPTED)
        mark_branch_handoff_decision_outcome(
            runtime=runtime,
            decision=handoff_decision,
            run_status=RunStatus.INTERRUPTED.value,
            run_id=run_id,
            message=message or _message_text_from_graph_payload(payload),
            error="CancelledError",
        )
        record = runtime.run_manager.get(run_id)
        if record is None or not record.abort_event.is_set():
            await publish("run.failed", error="CancelledError", message="Run was cancelled.")
    except Exception as exc:  # noqa: BLE001
        record = runtime.run_manager.get(run_id)
        if record is not None and record.abort_event.is_set() and _is_cancel_cleanup_exception(exc):
            await runtime.run_manager.set_status(run_id, RunStatus.INTERRUPTED)
            mark_branch_handoff_decision_outcome(
                runtime=runtime,
                decision=handoff_decision,
                run_status=RunStatus.INTERRUPTED.value,
                run_id=run_id,
                message=message or _message_text_from_graph_payload(payload),
                error=str(exc),
            )
            return
        mark_branch_handoff_decision_outcome(
            runtime=runtime,
            decision=handoff_decision,
            run_status=RunStatus.ERROR.value,
            run_id=run_id,
            message=message or _message_text_from_graph_payload(payload),
            error=str(exc),
        )
        await runtime.run_manager.set_status(run_id, RunStatus.ERROR, error=str(exc))
        failed_values = _safe_chat_values(chat=chat, thread_id=thread_id)
        _record_harness_turn_and_schedule(
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
            payload=payload,
            error=str(exc),
        )
        await publish(
            "run.failed",
            error=exc.__class__.__name__,
            message=str(exc),
            **_task_outcome_event_payload(failed_values.get("task_outcome")),
        )
    finally:
        await _close_run_stream(
            runtime=runtime,
            run_id=run_id,
            thread_id=thread_id,
            sequence=sequence,
        )


async def _produce_branch_action_run_stream(
    *,
    runtime: AppRuntime,
    chat: ChatService,
    run_id: str,
    thread_id: str,
    user_id: str,
    message: str,
    request_id: str | None,
    context: Any,
    branch_meta: Any,
    initial_values: dict[str, Any],
    kind: str = "chat.turn",
) -> None:
    sequence = 0
    initial_message_count, initial_llm_calls, started_at = _turn_recording_baseline(initial_values)
    input_messages = [HumanMessage(content=message)]
    trace_correlation = _trace_correlation(runtime=runtime, request_id=request_id)

    async def publish(event_name: str, source_node_name: str = "harness", **data: Any) -> None:
        nonlocal sequence
        sequence = await _publish_run_event(
            runtime=runtime,
            run_id=run_id,
            thread_id=thread_id,
            sequence=sequence,
            event_name=event_name,
            source_node_name=source_node_name,
            data=data,
        )

    try:
        await runtime.run_manager.set_status(run_id, RunStatus.RUNNING)
        await publish("run.metadata")
        await publish("run.status", phase="running")
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
        final_task_outcome = final_values.get("task_outcome")
        message_text = str(result.get("message") or "")
        if message_text and not looks_like_textual_tool_call_artifact(result["message"]):
            await publish(
                "message.completed",
                content=message_text,
                source="branch_action",
                **_task_outcome_event_payload(final_task_outcome),
            )
        _record_harness_turn_and_schedule(
            chat=chat,
            thread_id=thread_id,
            user_id=user_id,
            root_thread_id=latest_context.root_thread_id,
            kind=kind,
            status="succeeded",
            final_values=final_values,
            initial_message_count=initial_message_count,
            initial_llm_calls=initial_llm_calls,
            started_at=started_at,
            branch_meta=latest_branch_meta,
            trace_correlation=trace_correlation,
            payload={"messages": input_messages},
            answer=message_text or None,
            schedule_side_effects=False,
        )
        await runtime.run_manager.set_status(run_id, RunStatus.SUCCESS)
        await publish(
            "run.completed",
            status="succeeded",
            thread_state=result.get("thread_state"),
            branch_action=result.get("branch_action"),
            branch_record=result.get("branch_record"),
            navigation=result.get("navigation"),
            **_task_outcome_event_payload(final_task_outcome),
        )
    except asyncio.CancelledError:
        await runtime.run_manager.set_status(run_id, RunStatus.INTERRUPTED)
        record = runtime.run_manager.get(run_id)
        if record is None or not record.abort_event.is_set():
            await publish("run.failed", error="CancelledError", message="Run was cancelled.")
    except Exception as exc:  # noqa: BLE001
        record = runtime.run_manager.get(run_id)
        if record is not None and record.abort_event.is_set() and _is_cancel_cleanup_exception(exc):
            await runtime.run_manager.set_status(run_id, RunStatus.INTERRUPTED)
            return
        await runtime.run_manager.set_status(run_id, RunStatus.ERROR, error=str(exc))
        failed_values = _safe_chat_values(chat=chat, thread_id=thread_id)
        _record_harness_turn_and_schedule(
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
            payload={"messages": input_messages},
            error=str(exc),
        )
        await publish(
            "run.failed",
            error=exc.__class__.__name__,
            message=str(exc),
            **_task_outcome_event_payload(failed_values.get("task_outcome")),
        )
    finally:
        await _close_run_stream(
            runtime=runtime,
            run_id=run_id,
            thread_id=thread_id,
            sequence=sequence,
        )
