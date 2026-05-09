from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from langchain.messages import AIMessage, HumanMessage
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field

from focus_agent.engine.runtime import AppRuntime
from focus_agent.harness.runtime import DisconnectMode, MultitaskStrategy, RunConflictError, RunStatus
from focus_agent.harness.streaming import END_SENTINEL, HEARTBEAT_SENTINEL, canonical_event_payload, sse_frame
from focus_agent.observability.tracing import build_invoke_config, build_trace_correlation
from focus_agent.security.tokens import Principal
from focus_agent.services.chat import ChatService
from focus_agent.services.chat_streaming import stream_graph_chunks
from focus_agent.transport.stream_events import (
    extract_reasoning_delta,
    extract_tool_call_chunks,
    extract_tool_requests_from_updates,
    extract_tool_results_from_updates,
    extract_visible_text_delta,
    map_custom_payload_to_event,
    sanitize_stream_metadata,
)

from ..deps import get_app_runtime, get_chat_service, get_current_principal

router = APIRouter(prefix="/v2", tags=["harness-runs"])

_INTERNAL_MESSAGE_STREAM_NODES = frozenset({"plan", "reflect"})
_TOOL_RESULT_FALLBACK_VISIBLE_PREFIX = "我先根据已拿到的工具结果给出一个保守整理："


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
    graph_payload, context, branch_meta, initial_values, skill_hints = _prepare_run_payload(
        thread_id=thread_id,
        user_id=principal.user_id,
        payload=payload,
        chat=chat,
    )
    message = _message_from_payload(payload)
    run_record = await _create_run_record(
        runtime=runtime,
        payload=payload,
        thread_id=thread_id,
        user_id=principal.user_id,
        graph_payload=graph_payload,
    )
    await runtime.run_manager.set_status(run_record.run_id, RunStatus.RUNNING)
    if _branch_action_intent_for_run(
        chat=chat,
        initial_values=initial_values,
        branch_meta=branch_meta,
        message=message,
    ):
        try:
            result = await asyncio.to_thread(
                chat._handle_branch_action_turn,
                thread_id=thread_id,
                user_id=principal.user_id,
                message=message,
                request_id=getattr(request.state, "request_id", None),
            )
            if result is None:
                raise RuntimeError("Branch action intent disappeared before execution.")
        except Exception as exc:  # noqa: BLE001
            await runtime.run_manager.set_status(run_record.run_id, RunStatus.ERROR, error=str(exc))
            raise
        await runtime.run_manager.set_status(run_record.run_id, RunStatus.SUCCESS)
        del skill_hints
        return HarnessRunResponse(
            run=_run_record_payload(runtime.run_manager.get(run_record.run_id) or run_record),
            thread_state=result["thread_state"],
        )
    trace_correlation = build_trace_correlation(
        settings=runtime.settings,
        request_id=getattr(request.state, "request_id", None),
    )
    config = build_invoke_config(
        settings=runtime.settings,
        thread_id=thread_id,
        user_id=principal.user_id,
        root_thread_id=context.root_thread_id,
        branch_meta=branch_meta,
        trace_correlation=trace_correlation,
        run_name="focus_agent_harness_run",
    )
    try:
        await asyncio.to_thread(
            runtime.graph.invoke,
            graph_payload,
            config=config,
            context=context,
            version="v2",
        )
    except Exception as exc:  # noqa: BLE001
        await runtime.run_manager.set_status(run_record.run_id, RunStatus.ERROR, error=str(exc))
        raise
    await runtime.run_manager.set_status(run_record.run_id, RunStatus.SUCCESS)
    latest_context, latest_branch_meta, _ = chat._context_for_thread(
        thread_id=thread_id,
        user_id=principal.user_id,
    )
    thread_state = chat._response_payload(
        thread_id=thread_id,
        user_id=principal.user_id,
        context=latest_context,
        branch_meta=latest_branch_meta,
        interrupts=chat._safe_get_interrupts(thread_id),
        trace_correlation=trace_correlation,
    )
    del skill_hints
    return HarnessRunResponse(
        run=_run_record_payload(runtime.run_manager.get(run_record.run_id) or run_record),
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
    graph_payload, context, branch_meta, initial_values, _skill_hints = _prepare_run_payload(
        thread_id=thread_id,
        user_id=principal.user_id,
        payload=payload,
        chat=chat,
    )
    message = _message_from_payload(payload)
    run_record = await _create_run_record(
        runtime=runtime,
        payload=payload,
        thread_id=thread_id,
        user_id=principal.user_id,
        graph_payload=graph_payload,
    )
    if _branch_action_intent_for_run(
        chat=chat,
        initial_values=initial_values,
        branch_meta=branch_meta,
        message=message,
    ):
        producer = asyncio.create_task(
            _produce_branch_action_run_stream(
                runtime=runtime,
                chat=chat,
                run_id=run_record.run_id,
                thread_id=thread_id,
                user_id=principal.user_id,
                message=message,
                request_id=getattr(request.state, "request_id", None),
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
    run_record = await _create_run_record(
        runtime=runtime,
        payload=payload,
        thread_id=thread_id,
        user_id=principal.user_id,
        graph_payload=command,
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
    run_payload = await _load_run_payload(runtime, run_id)
    if run_payload is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    _authorize_run_access(chat=chat, principal=principal, run_payload=run_payload)
    return _run_event_streaming_response(
        runtime=runtime,
        run_id=run_id,
        thread_id=str(run_payload["thread_id"]),
        request=request,
        cancel_on_disconnect=False,
    )


@router.get("/runs/{run_id}", response_model=HarnessRunResponse)
async def get_harness_run(
    run_id: str,
    runtime: AppRuntime = Depends(get_app_runtime),
    chat: ChatService = Depends(get_chat_service),
    principal: Principal = Depends(get_current_principal),
) -> HarnessRunResponse:
    run_payload = await _load_run_payload(runtime, run_id)
    if run_payload is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    _authorize_run_access(chat=chat, principal=principal, run_payload=run_payload)
    return HarnessRunResponse(run=run_payload, thread_state=None)


@router.post("/runs/{run_id}/cancel", response_model=HarnessRunResponse)
async def cancel_harness_run(
    run_id: str,
    payload: HarnessRunCancelRequest,
    runtime: AppRuntime = Depends(get_app_runtime),
    chat: ChatService = Depends(get_chat_service),
    principal: Principal = Depends(get_current_principal),
) -> HarnessRunResponse:
    run_payload = await _load_run_payload(runtime, run_id)
    if run_payload is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    _authorize_run_access(chat=chat, principal=principal, run_payload=run_payload)
    action = "rollback" if payload.action == "rollback" else "interrupt"
    cancelled = await runtime.run_manager.cancel(run_id, action=action)
    if not cancelled:
        raise HTTPException(status_code=404, detail=f"Active run not found: {run_id}")
    record = runtime.run_manager.get(run_id)
    return HarnessRunResponse(
        run=_run_record_payload(record) if record else {"run_id": run_id},
        thread_state=None,
    )


def _prepare_run_payload(
    *,
    thread_id: str,
    user_id: str,
    payload: HarnessRunRequest,
    chat: ChatService,
) -> tuple[dict[str, Any], Any, Any, dict[str, Any], tuple[str, ...]]:
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
    selected_model = payload.model or chat.runtime.settings.model
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
    return graph_payload, context, branch_meta, initial_values, selection.skill_ids


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
) -> Any:
    try:
        return await runtime.run_manager.create_or_reject(
            thread_id,
            assistant_id=payload.metadata.get("assistant_id"),
            on_disconnect=DisconnectMode(payload.on_disconnect),
            metadata=dict(payload.metadata),
            kwargs={"input": _json_safe(graph_payload)},
            multitask_strategy=MultitaskStrategy(payload.multitask_strategy),
            user_id=user_id,
        )
    except RunConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


def _branch_action_intent_for_run(
    *,
    chat: ChatService,
    initial_values: dict[str, Any],
    branch_meta: Any,
    message: str,
) -> bool:
    return chat._branch_action_intent(values=initial_values, branch_meta=branch_meta, message=message) is not None


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
) -> None:
    sequence = 0
    visible_text_buffer = ""
    reasoning_buffer = ""
    cancelled = False
    initial_message_count = len(list(initial_values.get("messages", []) or []))
    trace_correlation = build_trace_correlation(settings=runtime.settings, request_id=request_id)
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
        sequence += 1
        await runtime.stream_bridge.publish(
            run_id,
            event_name,
            canonical_event_payload(
                run_id=run_id,
                thread_id=thread_id,
                turn_id=run_id,
                sequence=sequence,
                source_node=source_node_name,
                **_canonical_payload_extras(data),
            ),
        )

    try:
        await runtime.run_manager.set_status(run_id, RunStatus.RUNNING)
        await publish("run.metadata")
        await publish("run.status", phase="running")
        async for chunk in stream_graph_chunks(
            graph=runtime.graph,
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
                source_node = _source_node(safe_metadata, namespace)
                is_internal = source_node in _INTERNAL_MESSAGE_STREAM_NODES
                tool_chunks = extract_tool_call_chunks(message_chunk)
                visible_delta = extract_visible_text_delta(message_chunk)
                hide_visible_delta = (
                    is_internal
                    or bool(tool_chunks)
                    or _is_tool_result_fallback_visible_delta(visible_delta)
                )
                if visible_delta and not hide_visible_delta:
                    visible_text_buffer += visible_delta
                    await publish(
                        "message.delta",
                        source_node,
                        delta=visible_delta,
                        message_id=str(getattr(message_chunk, "id", None) or run_id),
                        metadata=safe_metadata,
                        namespace=namespace,
                    )
                reasoning_delta = extract_reasoning_delta(message_chunk)
                if reasoning_delta and not is_internal:
                    reasoning_buffer += reasoning_delta
                    await publish(
                        "reasoning.delta",
                        source_node,
                        delta=reasoning_delta,
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
                await publish("state.update", source_node, data=data, metadata=chunk_metadata, namespace=namespace)
                continue
            if chunk_type == "tasks":
                task_payload = data if isinstance(data, dict) else {"value": data}
                await publish("task.update", source_node, **task_payload, metadata=chunk_metadata, namespace=namespace)

        if cancelled:
            record = runtime.run_manager.get(run_id)
            await runtime.run_manager.set_status(run_id, RunStatus.INTERRUPTED)
            await publish(
                "run.interrupt",
                action=getattr(record, "abort_action", "interrupt") if record is not None else "interrupt",
            )
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
        final_visible_text = chat._latest_final_ai_text(appended_messages) or visible_text_buffer
        if final_visible_text:
            await publish(
                "message.completed",
                content=final_visible_text,
                source="graph_state" if _has_final_ai(appended_messages) else "stream_buffer",
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
        await publish("run.completed", status="succeeded", thread_state=thread_state)
    except asyncio.CancelledError:
        await runtime.run_manager.set_status(run_id, RunStatus.INTERRUPTED)
        record = runtime.run_manager.get(run_id)
        if record is not None and record.abort_event.is_set():
            await publish("run.interrupt", action=record.abort_action)
        else:
            await publish("run.failed", error="CancelledError", message="Run was cancelled.")
    except Exception as exc:  # noqa: BLE001
        await runtime.run_manager.set_status(run_id, RunStatus.ERROR, error=str(exc))
        await publish("run.failed", error=exc.__class__.__name__, message=str(exc))
    finally:
        sequence += 1
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


async def _produce_branch_action_run_stream(
    *,
    runtime: AppRuntime,
    chat: ChatService,
    run_id: str,
    thread_id: str,
    user_id: str,
    message: str,
    request_id: str | None,
) -> None:
    sequence = 0

    async def publish(event_name: str, source_node_name: str = "harness", **data: Any) -> None:
        nonlocal sequence
        sequence += 1
        await runtime.stream_bridge.publish(
            run_id,
            event_name,
            canonical_event_payload(
                run_id=run_id,
                thread_id=thread_id,
                turn_id=run_id,
                sequence=sequence,
                source_node=source_node_name,
                **_canonical_payload_extras(data),
            ),
        )

    try:
        await runtime.run_manager.set_status(run_id, RunStatus.RUNNING)
        await publish("run.metadata")
        await publish("run.status", phase="running")
        result = await asyncio.to_thread(
            chat._handle_branch_action_turn,
            thread_id=thread_id,
            user_id=user_id,
            message=message,
            request_id=request_id,
        )
        if result is None:
            raise RuntimeError("Branch action intent disappeared before execution.")
        if result.get("message"):
            await publish(
                "message.completed",
                content=str(result["message"]),
                source="branch_action",
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
        if record is not None and record.abort_event.is_set():
            await publish("run.interrupt", action=record.abort_action)
        else:
            await publish("run.failed", error="CancelledError", message="Run was cancelled.")
    except Exception as exc:  # noqa: BLE001
        await runtime.run_manager.set_status(run_id, RunStatus.ERROR, error=str(exc))
        await publish("run.failed", error=exc.__class__.__name__, message=str(exc))
    finally:
        sequence += 1
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


def _message_from_payload(payload: HarnessRunRequest) -> str:
    if payload.message is not None:
        return payload.message
    if payload.input and payload.input.get("message") is not None:
        return str(payload.input["message"])
    raise HTTPException(status_code=400, detail="Harness run requires a message.")


def _source_node(metadata: dict[str, Any], namespace: list[str]) -> str:
    return str(metadata.get("langgraph_node") or (namespace[-1] if namespace else "") or "harness")


def _canonical_custom_event(event: str, payload: dict[str, Any]) -> str:
    if event in {"tool.requested", "tool.result", "tool.error"}:
        if not (payload.get("tool_call_id") or payload.get("id")):
            return "state.update"
        return event
    if event in {"run.status", "state.update"}:
        return event
    return "state.update"


def _canonical_payload_extras(data: dict[str, Any]) -> dict[str, Any]:
    reserved = {"run_id", "thread_id", "turn_id", "sequence", "source_node"}
    return {key: value for key, value in data.items() if key not in reserved}


def _tool_result_is_error(item: dict[str, Any]) -> bool:
    content = str(item.get("content") or "").lower()
    return '"status": "error"' in content or '"status":"error"' in content


def _has_final_ai(messages: list[Any]) -> bool:
    return any(isinstance(message, AIMessage) and not getattr(message, "tool_calls", None) for message in messages)


def _is_tool_result_fallback_visible_delta(delta: str) -> bool:
    return delta.lstrip().startswith(_TOOL_RESULT_FALLBACK_VISIBLE_PREFIX)


def _json_safe(value: Any) -> Any:
    if hasattr(value, "value") and hasattr(value, "interrupts"):
        return _json_safe(value.value)
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json")
        except Exception:  # noqa: BLE001
            return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _run_record_payload(record: Any) -> dict[str, Any]:
    if hasattr(record, "to_dict"):
        return _json_safe(record.to_dict())
    return _json_safe(record)


async def _load_run_payload(runtime: AppRuntime, run_id: str) -> dict[str, Any] | None:
    record = runtime.run_manager.get(run_id)
    if record is not None:
        return _run_record_payload(record)
    return await _get_persisted_run(runtime, run_id)


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


async def _get_persisted_run(runtime: AppRuntime, run_id: str) -> dict[str, Any] | None:
    event_store = getattr(runtime, "event_store", None)
    get_run = getattr(event_store, "get_run", None)
    if not callable(get_run):
        return None
    run = await get_run(run_id)
    if run is None:
        return None
    if hasattr(run, "to_dict"):
        return _json_safe(run.to_dict())
    return _json_safe(run)


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

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
