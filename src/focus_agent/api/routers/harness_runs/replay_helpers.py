from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.responses import StreamingResponse
from langchain.messages import HumanMessage
from langgraph.types import Command

from focus_agent.core.async_threads import call_in_daemon_thread
from focus_agent.core.repo_call import has_repo_method
from focus_agent.engine.runtime import AppRuntime
from focus_agent.harness.runtime import (
    DisconnectMode,
    MultitaskStrategy,
    RunConflictError,
    UnsupportedStrategyError,
)
from focus_agent.harness.runtime.rollback import (
    ROLLBACK_TARGET_METADATA_KEY,
    CheckpointRollbackTarget,
    capture_checkpoint_rollback_target,
)
from focus_agent.harness.streaming import (
    END_SENTINEL,
    HEARTBEAT_SENTINEL,
    canonical_event_payload,
    sse_frame,
)
from focus_agent.observability.tracing import build_trace_correlation
from focus_agent.observability.trajectory import utc_now
from focus_agent.runtime.lifecycle import is_shutting_down
from focus_agent.security.tokens import Principal
from focus_agent.services.branches.actions import branch_handoff_message_from_text
from focus_agent.services.chat import ChatService, ConcurrentTurnError

from ...route_utils.harness_run_helpers import (
    _canonical_custom_event,
    _canonical_payload_extras,
    _event_store_for_runtime,
    _get_persisted_run,
    _is_tool_result_fallback_visible_delta,
    _journal_method,
    _journal_method_optional,
    _json_safe,
    _run_record_payload,
    _safe_completed_visible_text,
    _should_hide_completed_visible_text,
    _source_node,
    _tool_result_is_error,
)
from ...streaming import sse_streaming_response
from .replay_models import HarnessResumeRequest, HarnessRunRequest, HarnessRunResponse

logger = logging.getLogger("focus_agent.api.harness_runs")

_ROLLBACK_CLOSE_WAIT_SECONDS = 10.0
_BRANCH_RECOMMENDATION_TIMEOUT_SECONDS = 5.0
_BRANCH_RECOMMENDATION_MAX_TIMEOUT_SECONDS = 60.0


def _prepare_run_payload(
    *,
    thread_id: str,
    user_id: str,
    payload: HarnessRunRequest,
    chat: ChatService,
) -> tuple[dict[str, Any], Any, Any, dict[str, Any]]:
    message = _run_message_from_payload(payload)
    selection = chat._select_skills_for_message(
        message=message,
        explicit_skill_hints=tuple(payload.skill_hints),
    )
    context, branch_meta, initial_values = chat._preflight_thread_access(
        thread_id=thread_id,
        user_id=user_id,
        explicit_skill_hints=selection.skill_ids,
        require_writable=True,
    )
    selected_model = payload.model
    if selected_model is None:
        selected_model = getattr(getattr(chat, "runtime", None), "settings", None)
        if selected_model is not None:
            selected_model = getattr(selected_model, "model", None)
    input_messages = _run_input_messages_for_state(
        message=message,
        payload=payload,
        initial_values=initial_values,
    )
    graph_payload: dict[str, Any] = {
        "messages": input_messages,
        "task_brief": selection.stripped_message or message,
        "active_skill_ids": list(selection.skill_ids),
        "selected_model": selected_model,
        "selected_thinking_mode": chat._effective_thinking_mode(
            model_id=selected_model,
            thinking_mode=payload.thinking_mode,
        ),
    }
    if payload.input:
        graph_payload.update(
            {key: value for key, value in payload.input.items() if key != "messages"}
        )
    if selection.prompt_mode is not None:
        graph_payload["prompt_mode"] = selection.prompt_mode
    return graph_payload, context, branch_meta, initial_values


def _run_input_messages_for_state(
    *,
    message: str,
    payload: HarnessRunRequest,
    initial_values: dict[str, Any],
) -> list[HumanMessage]:
    if _is_branch_handoff_auto_run(payload) and _latest_human_message_matches(
        initial_values.get("messages"),
        message,
    ):
        return []
    return [HumanMessage(content=message)]


def _latest_human_message_matches(messages: Any, text: str) -> bool:
    normalized = _normalized_message_text(text)
    if not normalized:
        return False
    for message in reversed(list(messages or [])):
        if isinstance(message, HumanMessage):
            return _normalized_message_text(message.content) == normalized
        if isinstance(message, dict):
            message_type = str(message.get("type") or message.get("role") or "").lower()
            if message_type in {"human", "user"}:
                return _normalized_message_text(message.get("content")) == normalized
            if message_type in {"ai", "assistant", "tool"}:
                return False
            continue
        message_type = str(
            getattr(message, "type", message.__class__.__name__.replace("Message", "").lower())
            or ""
        ).lower()
        if message_type == "human":
            return _normalized_message_text(getattr(message, "content", "")) == normalized
        if message_type in {"ai", "assistant", "tool"}:
            return False
    return False


def _normalized_message_text(value: Any) -> str:
    if isinstance(value, list):
        text = " ".join(
            str(item.get("text") or item.get("content") or item)
            if isinstance(item, dict)
            else str(item)
            for item in value
            if item is not None
        )
    elif isinstance(value, dict):
        text = str(value.get("text") or value.get("content") or "")
    else:
        text = str(value or "")
    return " ".join(text.split())


def _prepare_resume_payload(
    *,
    thread_id: str,
    user_id: str,
    payload: HarnessResumeRequest,
    chat: ChatService,
) -> tuple[Command, Any, Any, dict[str, Any]]:
    context, branch_meta, initial_values = chat._preflight_thread_access(
        thread_id=thread_id,
        user_id=user_id,
        explicit_skill_hints=(),
        require_writable=True,
    )
    return Command(resume=payload.resume), context, branch_meta, initial_values


async def _create_run_record(
    *,
    runtime: AppRuntime,
    payload: HarnessRunRequest | HarnessResumeRequest,
    thread_id: str,
    user_id: str,
    graph_payload: Any,
    rollback_target: CheckpointRollbackTarget | None = None,
    rollback_partial: bool = False,
    rollback_unreverted_scopes: tuple[str, ...] = (),
) -> Any:
    metadata = dict(payload.metadata)
    if rollback_target is not None:
        metadata[ROLLBACK_TARGET_METADATA_KEY] = rollback_target.to_metadata()
    if rollback_partial:
        metadata["harness.rollback_partial"] = True
    if rollback_unreverted_scopes:
        metadata["harness.rollback_unreverted_scopes"] = list(rollback_unreverted_scopes)
    try:
        return await runtime.run_manager.create_or_reject(
            thread_id,
            assistant_id=payload.metadata.get("assistant_id"),
            on_disconnect=DisconnectMode(payload.on_disconnect),
            metadata=metadata,
            kwargs={"input": _json_safe(graph_payload)},
            multitask_strategy=MultitaskStrategy(payload.multitask_strategy),
            user_id=user_id,
            rollback_target=rollback_target,
        )
    except RunConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except UnsupportedStrategyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _capture_run_rollback_target(
    *,
    runtime: AppRuntime,
    thread_id: str,
) -> CheckpointRollbackTarget | None:
    try:
        harness = getattr(runtime, "harness", None)
        graph = getattr(harness, "graph", None)
        if graph is None:
            graph = getattr(runtime, "graph", None)
        if graph is None:
            return None
        return capture_checkpoint_rollback_target(graph, thread_id)
    except Exception:  # noqa: BLE001
        return None


def _branch_action_intent_for_run(
    *,
    chat: ChatService,
    initial_values: dict[str, Any],
    branch_meta: Any,
    message: str,
) -> bool:
    return (
        chat._branch_action_intent(values=initial_values, branch_meta=branch_meta, message=message)
        is not None
    )


def _handle_branch_recommendation_for_run(
    *,
    chat: ChatService,
    thread_id: str,
    user_id: str,
    message: str,
    request_id: str | None,
) -> dict[str, Any] | None:
    method_name = (
        "_handle_branch_recommendation_turn_with_lease"
        if has_repo_method(chat, "_handle_branch_recommendation_turn_with_lease")
        else "_handle_branch_recommendation_turn"
    )
    if not has_repo_method(chat, method_name):
        return None
    try:
        result = getattr(chat, method_name)(
            thread_id=thread_id,
            user_id=user_id,
            message=message,
            request_id=request_id,
        )
    except ConcurrentTurnError:
        logger.debug("pre-turn branch recommendation skipped because thread is busy")
        return None
    except Exception:  # noqa: BLE001 - recommendation failures must not block answers.
        logger.warning("pre-turn branch recommendation failed", exc_info=True)
        return None
    return result if isinstance(result, dict) else None


def _branch_recommendation_timeout_seconds(settings: Any) -> float:
    raw_timeout = getattr(
        settings,
        "agent_branch_recommendation_timeout_seconds",
        _BRANCH_RECOMMENDATION_TIMEOUT_SECONDS,
    )
    try:
        timeout = float(raw_timeout)
    except (TypeError, ValueError):
        return _BRANCH_RECOMMENDATION_TIMEOUT_SECONDS
    if timeout <= 0:
        return _BRANCH_RECOMMENDATION_TIMEOUT_SECONDS
    return min(timeout, _BRANCH_RECOMMENDATION_MAX_TIMEOUT_SECONDS)


async def _handle_branch_recommendation_for_run_async(
    *,
    timeout_seconds: float | None = None,
    **kwargs: Any,
) -> dict[str, Any] | None:
    timeout = (
        _BRANCH_RECOMMENDATION_TIMEOUT_SECONDS
        if timeout_seconds is None
        else max(0.001, float(timeout_seconds))
    )
    try:
        return await asyncio.wait_for(
            call_in_daemon_thread(
                _handle_branch_recommendation_for_run,
                wait_on_cancel=False,
                **kwargs,
            ),
            timeout=timeout,
        )
    except TimeoutError:
        logger.warning(
            "pre-turn branch recommendation timed out after %.1fs",
            timeout,
        )
        return None


async def _run_branch_action_turn_to_completion(
    *,
    chat: ChatService,
    thread_id: str,
    user_id: str,
    message: str,
    request_id: str | None,
) -> dict[str, Any] | None:
    worker = asyncio.create_task(
        asyncio.to_thread(
            chat._handle_branch_action_turn,
            thread_id=thread_id,
            user_id=user_id,
            message=message,
            request_id=request_id,
        )
    )
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        current_task = asyncio.current_task()
        uncancel = getattr(current_task, "uncancel", None) if current_task is not None else None
        if current_task is not None and callable(uncancel):
            for _ in range(current_task.cancelling()):
                uncancel()
        return await asyncio.shield(worker)


def _record_harness_turn_and_schedule(
    *,
    chat: ChatService,
    thread_id: str,
    user_id: str,
    root_thread_id: str,
    kind: str,
    status: str,
    final_values: dict[str, Any],
    initial_message_count: int,
    initial_llm_calls: int,
    started_at: Any,
    branch_meta: Any,
    trace_correlation: Any,
    payload: Any,
    answer: str | None = None,
    error: str | None = None,
    schedule_side_effects: bool = True,
) -> None:
    _call_chat_hook(
        chat=chat,
        method="_record_turn_trajectory_best_effort",
        thread_id=thread_id,
        user_id=user_id,
        root_thread_id=root_thread_id,
        kind=kind,
        status=status,
        final_values=final_values,
        initial_message_count=initial_message_count,
        initial_llm_calls=initial_llm_calls,
        started_at=started_at,
        finished_at=utc_now(),
        branch_meta=branch_meta,
        trace_correlation=trace_correlation,
        input_messages=list(payload.get("messages", []) if isinstance(payload, dict) else []),
        answer=answer,
        error=error,
    )
    if status != "succeeded" or not schedule_side_effects:
        return
    _call_chat_hook(
        chat=chat,
        method="_schedule_post_turn_context_compaction",
        thread_id=thread_id,
        user_id=user_id,
        kind=kind,
    )
    _call_chat_hook(
        chat=chat,
        method="_schedule_branch_name_refresh_after_first_turn",
        thread_id=thread_id,
        user_id=user_id,
        branch_meta=branch_meta,
        kind=kind,
    )


def _turn_recording_baseline(initial_values: dict[str, Any]) -> tuple[int, int, Any]:
    return (
        len(list(initial_values.get("messages", []) or [])),
        int(initial_values.get("llm_calls") or 0),
        utc_now(),
    )


def _trace_correlation(*, runtime: AppRuntime, request_id: str | None) -> Any:
    return build_trace_correlation(
        settings=getattr(runtime, "settings", {}),
        request_id=request_id,
    )


def _context_for_turn(
    *,
    chat: ChatService,
    thread_id: str,
    user_id: str,
    fallback_context: Any,
    fallback_branch_meta: Any,
) -> tuple[Any, Any, dict[str, Any]]:
    context_for_thread = _call_chat_hook(
        chat=chat,
        method="_context_for_thread",
        thread_id=thread_id,
        user_id=user_id,
    )
    if context_for_thread is not None:
        return context_for_thread
    return fallback_context, fallback_branch_meta, _safe_chat_values(chat=chat, thread_id=thread_id)


def _safe_chat_values(*, chat: ChatService, thread_id: str) -> dict[str, Any]:
    return dict(
        _safe_call_chat_hook(
            chat=chat,
            method="_safe_get_values",
            thread_id=thread_id,
            default={},
        )
        or {}
    )


def _call_chat_hook(
    chat: ChatService,
    method: str,
    *args: Any,
    **kwargs: Any,
) -> Any | None:
    if not has_repo_method(chat, method):
        return None
    return getattr(chat, method)(*args, **kwargs)


def _safe_call_chat_hook(
    chat: ChatService,
    method: str,
    *args: Any,
    default: Any = None,
    **kwargs: Any,
) -> Any:
    if not has_repo_method(chat, method):
        return default
    try:
        return getattr(chat, method)(*args, **kwargs)
    except Exception:  # noqa: BLE001
        return default


def _message_from_payload(payload: HarnessRunRequest) -> str:
    if payload.message is not None:
        return payload.message
    if payload.input and payload.input.get("message") is not None:
        return str(payload.input["message"])
    raise HTTPException(status_code=400, detail="Harness run requires a message.")


def _run_message_from_payload(payload: HarnessRunRequest) -> str:
    message = _message_from_payload(payload)
    if not _is_branch_handoff_auto_run(payload):
        return message
    return branch_handoff_message_from_text(message) or message


def _is_branch_handoff_auto_run(payload: HarnessRunRequest) -> bool:
    return bool((payload.metadata or {}).get("branch_handoff_auto_run"))


def _message_text_from_graph_payload(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    messages = list(payload.get("messages") or [])
    if not messages:
        return ""
    first = messages[0]
    content = first.get("content") if isinstance(first, dict) else getattr(first, "content", "")
    if isinstance(content, list):
        return " ".join(
            str(item.get("text") or item.get("content") or item)
            for item in content
            if item is not None
        ).strip()
    return str(content or "").strip()


async def _next_run_sequence(
    *,
    runtime: Any,
    run_id: str,
    current_sequence: int,
) -> int:
    count_events = _journal_method_optional(runtime, "count_events")
    if count_events is not None:
        try:
            journal_sequence = int(await count_events(run_id)) + 1
            return max(current_sequence + 1, journal_sequence)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to read harness journal sequence for run %s", run_id, exc_info=True
            )
    return current_sequence + 1


async def _publish_run_event(
    *,
    runtime: AppRuntime,
    run_id: str,
    thread_id: str,
    sequence: int,
    event_name: str,
    source_node_name: str | None,
    data: dict[str, Any],
) -> int:
    next_sequence = await _next_run_sequence(
        runtime=runtime,
        run_id=run_id,
        current_sequence=sequence,
    )
    await runtime.stream_bridge.publish(
        run_id,
        event_name,
        canonical_event_payload(
            run_id=run_id,
            thread_id=thread_id,
            turn_id=run_id,
            sequence=next_sequence,
            source_node=source_node_name,
            **_canonical_payload_extras(data),
        ),
    )
    return next_sequence


def _signal_rollback_ready(
    *,
    runtime: Any,
    run_id: str,
) -> None:
    record = runtime.run_manager.get(run_id)
    if record is None or getattr(record, "abort_action", "interrupt") != "rollback":
        return
    rollback_ready = getattr(record, "rollback_ready", None)
    if rollback_ready is not None:
        rollback_ready.set()


async def _await_rollback_completion(
    *,
    runtime: Any,
    run_id: str,
) -> None:
    record = runtime.run_manager.get(run_id)
    if record is None:
        return
    if getattr(record, "abort_action", "interrupt") != "rollback":
        return
    rollback_completed = getattr(record, "rollback_completed", None)
    if rollback_completed is None:
        return
    if rollback_completed.is_set():
        return
    try:
        await asyncio.wait_for(
            rollback_completed.wait(),
            timeout=_ROLLBACK_CLOSE_WAIT_SECONDS,
        )
    except TimeoutError:
        logger.warning(
            "Timed out waiting for rollback completion before closing run stream %s",
            run_id,
        )


async def _close_run_stream(
    *,
    runtime: AppRuntime,
    run_id: str,
    thread_id: str,
    sequence: int,
) -> None:
    _signal_rollback_ready(runtime=runtime, run_id=run_id)
    await _await_rollback_completion(runtime=runtime, run_id=run_id)
    sequence = await _next_run_sequence(
        runtime=runtime,
        run_id=run_id,
        current_sequence=sequence,
    )
    await runtime.stream_bridge.publish(
        run_id,
        "run.closed",
        canonical_event_payload(
            run_id=run_id,
            thread_id=thread_id,
            turn_id=run_id,
            sequence=sequence,
            source_node="harness",
            status="closed",
        ),
    )
    await runtime.stream_bridge.publish_end(run_id)


def _harness_run_response(
    *,
    runtime: AppRuntime,
    run_id: str,
    fallback_record: Any,
    thread_state: dict[str, Any] | None = None,
) -> HarnessRunResponse:
    return HarnessRunResponse(
        run=_run_record_payload(runtime.run_manager.get(run_id) or fallback_record),
        thread_state=thread_state,
    )


async def _load_run_payload(runtime: AppRuntime, run_id: str) -> dict[str, Any] | None:
    record = runtime.run_manager.get(run_id)
    if record is not None:
        return _run_record_payload(record)
    return await _get_persisted_run(runtime, run_id)


async def _load_authorized_run_payload(
    *,
    runtime: AppRuntime,
    chat: ChatService,
    principal: Principal,
    run_id: str,
) -> dict[str, Any]:
    run_payload = await _load_run_payload(runtime, run_id)
    if run_payload is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    _authorize_run_access(chat=chat, principal=principal, run_payload=run_payload)
    return run_payload


def _authorize_run_access(
    *,
    chat: ChatService,
    principal: Principal,
    run_payload: dict[str, Any],
) -> None:
    run_user_id = run_payload.get("user_id")
    if run_user_id is not None and str(run_user_id) != principal.user_id:
        raise HTTPException(status_code=403, detail="Run belongs to another user.")
    thread_id = run_payload.get("thread_id")
    if not isinstance(thread_id, str) or not thread_id:
        raise HTTPException(status_code=404, detail="Run thread not found.")
    try:
        chat._preflight_thread_access(
            thread_id=thread_id,
            user_id=principal.user_id,
            explicit_skill_hints=(),
            require_writable=False,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _run_event_streaming_response(
    *,
    runtime: AppRuntime,
    run_id: str,
    thread_id: str,
    request: Request,
    cancel_on_disconnect: bool,
) -> StreamingResponse:
    async def event_stream() -> AsyncIterator[str]:
        last_event_id = request.headers.get("last-event-id")
        heartbeat_sequence = 0
        try:
            async for event in runtime.stream_bridge.subscribe(
                run_id,
                last_event_id=last_event_id,
                heartbeat_interval=runtime.settings.sse_heartbeat_seconds,
            ):
                if is_shutting_down():
                    yield sse_frame(
                        event="server_shutdown",
                        data={
                            "run_id": run_id,
                            "thread_id": thread_id,
                            "turn_id": run_id,
                            "source_node": "harness",
                            "message": "server is shutting down",
                        },
                    )
                    break
                if event is HEARTBEAT_SENTINEL:
                    heartbeat_sequence += 1
                    yield sse_frame(
                        event="heartbeat",
                        data={
                            "run_id": run_id,
                            "thread_id": thread_id,
                            "turn_id": run_id,
                            "sequence": heartbeat_sequence,
                            "source_node": "harness",
                        },
                    )
                    continue
                if event is END_SENTINEL:
                    break
                yield sse_frame(event=event.event, event_id=event.id, data=event.data)
        finally:
            if cancel_on_disconnect:
                record = runtime.run_manager.get(run_id)
                if record is not None and record.inflight:
                    if record.on_disconnect is DisconnectMode.CANCEL:
                        await runtime.run_manager.cancel(run_id, action="interrupt")
                    elif record.on_disconnect is DisconnectMode.ROLLBACK:
                        await runtime.run_manager.cancel(run_id, action="rollback")

    return sse_streaming_response(event_stream())


__all__ = [
    "_canonical_custom_event",
    "_canonical_payload_extras",
    "_event_store_for_runtime",
    "_get_persisted_run",
    "_is_tool_result_fallback_visible_delta",
    "_journal_method",
    "_journal_method_optional",
    "_json_safe",
    "_run_record_payload",
    "_safe_completed_visible_text",
    "_should_hide_completed_visible_text",
    "_source_node",
    "_tool_result_is_error",
    "_authorize_run_access",
    "_branch_action_intent_for_run",
    "_branch_recommendation_timeout_seconds",
    "_call_chat_hook",
    "_capture_run_rollback_target",
    "_close_run_stream",
    "_context_for_turn",
    "_create_run_record",
    "_handle_branch_recommendation_for_run",
    "_handle_branch_recommendation_for_run_async",
    "_harness_run_response",
    "_is_branch_handoff_auto_run",
    "_load_authorized_run_payload",
    "_load_run_payload",
    "_message_from_payload",
    "_message_text_from_graph_payload",
    "_next_run_sequence",
    "_prepare_resume_payload",
    "_prepare_run_payload",
    "_publish_run_event",
    "_record_harness_turn_and_schedule",
    "_run_branch_action_turn_to_completion",
    "_run_event_streaming_response",
    "_run_message_from_payload",
    "_safe_call_chat_hook",
    "_safe_chat_values",
    "_trace_correlation",
    "_turn_recording_baseline",
    "build_trace_correlation",
    "canonical_event_payload",
    "HTTPException",
    "UnsupportedStrategyError",
]
