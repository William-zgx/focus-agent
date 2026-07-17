from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.responses import StreamingResponse

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
    StreamProxy,
    StreamProxyConfig,
    canonical_event_payload,
    sse_frame,
)
from focus_agent.observability.tracing import build_trace_correlation
from focus_agent.observability.trajectory import utc_now
from focus_agent.runtime.lifecycle import is_shutting_down
from focus_agent.security.tokens import Principal
from focus_agent.services.chat import ChatService, ConcurrentTurnError
from focus_agent.transport.stream_events import sanitize_stream_metadata

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
from .replay_payloads import (
    _is_branch_handoff_auto_run,
    _latest_human_message_matches,
    _message_from_payload,
    _message_text_from_graph_payload,
    _normalized_message_text,
    _prepare_resume_payload,
    _prepare_run_payload,
    _run_input_messages_for_state,
    _run_message_from_payload,
)

logger = logging.getLogger("focus_agent.api.harness_runs")

_ROLLBACK_CLOSE_WAIT_SECONDS = 10.0
_BRANCH_RECOMMENDATION_TIMEOUT_SECONDS = 5.0
_BRANCH_RECOMMENDATION_MAX_TIMEOUT_SECONDS = 60.0


def _task_stream_event_payload(
    data: Any,
    chunk_metadata: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = dict(data) if isinstance(data, dict) else {"value": data}
    payload_metadata = payload.pop("metadata", None)
    metadata = sanitize_stream_metadata(
        payload_metadata if isinstance(payload_metadata, dict) else None
    )
    metadata.update(chunk_metadata)
    return payload, metadata


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


def _should_optimize_stream(request: Request) -> bool:
    """Decide whether to apply the StreamProxy for this SSE connection.

    The proxy is opt-in: it is only enabled when the caller explicitly asks
    for it. We honor, in priority order:
      1. ``?optimize_stream=true`` query parameter.
      2. ``X-Stream-Optimize: 1|true|yes`` request header.
      3. ``Accept`` header containing the token ``stream-optimized`` (allows
         web clients to request it via EventSource's fetch polyfill).
      4. ``X-Stream-Optimize-Auto: 1`` **combined** with a browser UA lets
         the frontend opt itself into auto-detection without forcing
         optimization on all browsers.

    Defaults to ``False`` so existing clients are unaffected.
    """
    try:
        qp = request.query_params.get("optimize_stream")
        if qp is not None and str(qp).strip().lower() in {"1", "true", "yes", "on"}:
            return True
        hdr = request.headers.get("x-stream-optimize")
        if hdr is not None and str(hdr).strip().lower() in {"1", "true", "yes", "on"}:
            return True
        accept = (request.headers.get("accept") or "").lower()
        if "stream-optimized" in accept:
            return True
        auto = request.headers.get("x-stream-optimize-auto")
        if auto is not None and str(auto).strip().lower() in {"1", "true", "yes", "on"}:
            ua = (request.headers.get("user-agent") or "").lower()
            if ua.startswith("mozilla/"):
                return True
    except Exception:  # noqa: BLE001 - never break SSE over header parsing
        return False
    return False


def _build_stream_proxy(request: Request) -> StreamProxy | None:
    if not _should_optimize_stream(request):
        return None
    cfg = StreamProxyConfig(
        strip_redundant_fields=True,
        drop_empty_heartbeats=False,  # keep heartbeats for SSE liveness
        deduplicate_consecutive=True,
    )
    return StreamProxy(config=cfg)


def _run_event_streaming_response(
    *,
    runtime: AppRuntime,
    run_id: str,
    thread_id: str,
    request: Request,
    cancel_on_disconnect: bool,
) -> StreamingResponse:
    proxy = _build_stream_proxy(request)

    async def event_stream() -> AsyncIterator[str]:
        last_event_id = request.headers.get("last-event-id")
        heartbeat_sequence = 0
        try:
            async for event in runtime.stream_bridge.subscribe(
                run_id,
                last_event_id=last_event_id,
                heartbeat_interval=runtime.settings.sse_heartbeat_seconds,
            ):
                if proxy is not None:
                    event = proxy.process_event(event)
                    if event is None:
                        continue
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
    "_latest_human_message_matches",
    "_load_authorized_run_payload",
    "_load_run_payload",
    "_message_from_payload",
    "_message_text_from_graph_payload",
    "_next_run_sequence",
    "_normalized_message_text",
    "_prepare_resume_payload",
    "_prepare_run_payload",
    "_publish_run_event",
    "_record_harness_turn_and_schedule",
    "_run_branch_action_turn_to_completion",
    "_run_event_streaming_response",
    "_run_input_messages_for_state",
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
