from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from langchain.messages import HumanMessage
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field

from focus_agent.core.repo_call import has_repo_method
from focus_agent.core.tool_protocol import (
    looks_like_textual_tool_call_artifact,
    safe_visible_text_transition,
)
from focus_agent.engine.runtime import AppRuntime
from focus_agent.harness.runtime import (
    DisconnectMode,
    MultitaskStrategy,
    RunConflictError,
    RunStatus,
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
from focus_agent.observability.tracing import build_invoke_config, build_trace_correlation
from focus_agent.observability.trajectory import utc_now
from focus_agent.runtime.lifecycle import is_shutting_down
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

from ..deps import get_app_runtime, get_chat_service, get_current_principal
from ..route_utils.harness_run_helpers import (
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
from ..streaming import sse_streaming_response

router = APIRouter(prefix="/v2", tags=["harness-runs"])
logger = logging.getLogger("focus_agent.api.harness_runs")

_ROLLBACK_CLOSE_WAIT_SECONDS = 10.0

_INTERNAL_MESSAGE_STREAM_NODES = frozenset({"plan", "reflect"})


class HarnessRunRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    message: str | None = None
    input: dict[str, Any] | None = None
    model: str | None = None
    thinking_mode: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    skill_hints: list[str] = Field(default_factory=list)
    on_disconnect: Literal["cancel", "continue", "rollback"] = "cancel"
    multitask_strategy: Literal["reject", "interrupt", "rollback", "enqueue"] = "reject"


class HarnessRunResponse(BaseModel):
    run: dict[str, Any]
    thread_state: dict[str, Any] | None = None


class HarnessRunCancelRequest(BaseModel):
    action: Literal["interrupt", "rollback"] = "interrupt"


class HarnessResumeRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    resume: Any
    metadata: dict[str, Any] = Field(default_factory=dict)
    on_disconnect: Literal["cancel", "continue", "rollback"] = "cancel"
    multitask_strategy: Literal["reject", "interrupt", "rollback", "enqueue"] = "reject"


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
    message = _message_from_payload(payload)
    is_branch_action = _branch_action_intent_for_run(
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
) -> HarnessRunResponse:
    await runtime.run_manager.set_status(run_record.run_id, RunStatus.RUNNING)
    initial_message_count, initial_llm_calls, started_at = _turn_recording_baseline(initial_values)
    trace_correlation = _trace_correlation(runtime=runtime, request_id=request_id)
    try:
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
    message = _message_from_payload(payload)
    is_branch_action = _branch_action_intent_for_run(
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


@router.post("/runs/{run_id}/stream")
async def stream_existing_harness_run(
    run_id: str,
    request: Request,
    runtime: AppRuntime = Depends(get_app_runtime),
    chat: ChatService = Depends(get_chat_service),
    principal: Principal = Depends(get_current_principal),
) -> StreamingResponse:
    run_payload = await _load_authorized_run_payload(
        runtime=runtime,
        chat=chat,
        principal=principal,
        run_id=run_id,
    )
    return _run_event_streaming_response(
        runtime=runtime,
        run_id=run_id,
        thread_id=str(run_payload["thread_id"]),
        request=request,
        cancel_on_disconnect=False,
    )


@router.get("/runs/{run_id}/events")
async def list_harness_run_events(
    run_id: str,
    runtime: AppRuntime = Depends(get_app_runtime),
    chat: ChatService = Depends(get_chat_service),
    principal: Principal = Depends(get_current_principal),
    event: str | None = None,
    limit: int | None = Query(default=None, ge=1, le=5000),
) -> dict[str, Any]:
    run_payload = await _load_authorized_run_payload(
        runtime=runtime,
        chat=chat,
        principal=principal,
        run_id=run_id,
    )
    list_events = _journal_method(runtime, "list_events")
    events = await list_events(run_id, event=event, limit=limit)
    return {
        "run_id": run_id,
        "thread_id": run_payload["thread_id"],
        "events": [
            _json_safe(item.to_dict() if hasattr(item, "to_dict") else item) for item in events
        ],
    }


@router.get("/runs/{run_id}/snapshot")
async def get_harness_run_snapshot(
    run_id: str,
    runtime: AppRuntime = Depends(get_app_runtime),
    chat: ChatService = Depends(get_chat_service),
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    await _load_authorized_run_payload(
        runtime=runtime,
        chat=chat,
        principal=principal,
        run_id=run_id,
    )
    snapshot = await _journal_method(runtime, "snapshot")(run_id)
    return _json_safe(snapshot)


@router.get("/runs/{run_id}/trajectory")
async def get_harness_run_trajectory(
    run_id: str,
    runtime: AppRuntime = Depends(get_app_runtime),
    chat: ChatService = Depends(get_chat_service),
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    await _load_authorized_run_payload(
        runtime=runtime,
        chat=chat,
        principal=principal,
        run_id=run_id,
    )
    trajectory = await _journal_method(runtime, "trajectory_summary")(run_id)
    return _json_safe(trajectory)


@router.get("/runs/{run_id}", response_model=HarnessRunResponse)
async def get_harness_run(
    run_id: str,
    runtime: AppRuntime = Depends(get_app_runtime),
    chat: ChatService = Depends(get_chat_service),
    principal: Principal = Depends(get_current_principal),
) -> HarnessRunResponse:
    run_payload = await _load_authorized_run_payload(
        runtime=runtime,
        chat=chat,
        principal=principal,
        run_id=run_id,
    )
    return HarnessRunResponse(run=run_payload, thread_state=None)


@router.post("/runs/{run_id}/cancel", response_model=HarnessRunResponse)
async def cancel_harness_run(
    run_id: str,
    payload: HarnessRunCancelRequest,
    runtime: AppRuntime = Depends(get_app_runtime),
    chat: ChatService = Depends(get_chat_service),
    principal: Principal = Depends(get_current_principal),
) -> HarnessRunResponse:
    await _load_authorized_run_payload(
        runtime=runtime,
        chat=chat,
        principal=principal,
        run_id=run_id,
    )
    action = "rollback" if payload.action == "rollback" else "interrupt"
    cancelled = await runtime.run_manager.cancel(run_id, action=action)
    if not cancelled:
        raise HTTPException(status_code=404, detail=f"Active run not found: {run_id}")
    return _harness_run_response(
        runtime=runtime,
        run_id=run_id,
        fallback_record={"run_id": run_id},
    )


def _prepare_run_payload(
    *,
    thread_id: str,
    user_id: str,
    payload: HarnessRunRequest,
    chat: ChatService,
) -> tuple[dict[str, Any], Any, Any, dict[str, Any]]:
    message = _message_from_payload(payload)
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
    graph_payload: dict[str, Any] = {
        "messages": [HumanMessage(content=message)],
        "task_brief": selection.stripped_message or message,
        "active_skill_ids": list(selection.skill_ids),
        "selected_model": selected_model,
        "selected_thinking_mode": chat._effective_thinking_mode(
            model_id=selected_model,
            thinking_mode=payload.thinking_mode,
        ),
    }
    if payload.input:
        graph_payload.update(payload.input)
    if selection.prompt_mode is not None:
        graph_payload["prompt_mode"] = selection.prompt_mode
    return graph_payload, context, branch_meta, initial_values


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
    result = getattr(chat, method_name)(
        thread_id=thread_id,
        user_id=user_id,
        message=message,
        request_id=request_id,
    )
    return result if isinstance(result, dict) else None


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
) -> None:
    sequence = 0
    visible_text_buffer = ""
    visible_text_pending = ""
    reasoning_buffer = ""
    reasoning_text_pending = ""
    cancelled = False
    initial_message_count, initial_llm_calls, started_at = _turn_recording_baseline(initial_values)
    trace_correlation = _trace_correlation(runtime=runtime, request_id=request_id)
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
        if turn_message:
            branch_recommendation_result = _handle_branch_recommendation_for_run(
                chat=chat,
                thread_id=thread_id,
                user_id=user_id,
                message=turn_message,
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
            return

        latest_context, latest_branch_meta, final_values = chat._context_for_thread(
            thread_id=thread_id,
            user_id=user_id,
        )
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
            )
        if reasoning_buffer:
            await publish("reasoning.delta", delta="", completed=True, content=reasoning_buffer)
        await runtime.run_manager.set_status(run_id, RunStatus.SUCCESS)
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
        await publish("run.completed", status="succeeded", thread_state=thread_state)
    except asyncio.CancelledError:
        await runtime.run_manager.set_status(run_id, RunStatus.INTERRUPTED)
        record = runtime.run_manager.get(run_id)
        if record is None or not record.abort_event.is_set():
            await publish("run.failed", error="CancelledError", message="Run was cancelled.")
    except Exception as exc:  # noqa: BLE001
        await runtime.run_manager.set_status(run_id, RunStatus.ERROR, error=str(exc))
        _record_harness_turn_and_schedule(
            chat=chat,
            thread_id=thread_id,
            user_id=user_id,
            root_thread_id=context.root_thread_id,
            kind=kind,
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
        await publish("run.failed", error=exc.__class__.__name__, message=str(exc))
    finally:
        await _close_run_stream(
            runtime=runtime,
            run_id=run_id,
            thread_id=thread_id,
            sequence=sequence,
        )


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
        message_text = str(result.get("message") or "")
        if message_text and not looks_like_textual_tool_call_artifact(result["message"]):
            await publish(
                "message.completed",
                content=message_text,
                source="branch_action",
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
        )
    except asyncio.CancelledError:
        await runtime.run_manager.set_status(run_id, RunStatus.INTERRUPTED)
        record = runtime.run_manager.get(run_id)
        if record is None or not record.abort_event.is_set():
            await publish("run.failed", error="CancelledError", message="Run was cancelled.")
    except Exception as exc:  # noqa: BLE001
        await runtime.run_manager.set_status(run_id, RunStatus.ERROR, error=str(exc))
        _record_harness_turn_and_schedule(
            chat=chat,
            thread_id=thread_id,
            user_id=user_id,
            root_thread_id=context.root_thread_id,
            kind=kind,
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
        await publish("run.failed", error=exc.__class__.__name__, message=str(exc))
    finally:
        await _close_run_stream(
            runtime=runtime,
            run_id=run_id,
            thread_id=thread_id,
            sequence=sequence,
        )


def _message_from_payload(payload: HarnessRunRequest) -> str:
    if payload.message is not None:
        return payload.message
    if payload.input and payload.input.get("message") is not None:
        return str(payload.input["message"])
    raise HTTPException(status_code=400, detail="Harness run requires a message.")


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
    "HarnessResumeRequest",
    "HarnessRunCancelRequest",
    "HarnessRunRequest",
    "HarnessRunResponse",
    "router",
]
