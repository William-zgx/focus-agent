from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any, AsyncIterator

from ..core.branching import BranchMeta
from ..core.request_context import RequestContext
from ..observability.tracing import (
    TraceCorrelation,
    build_invoke_config,
    build_trace_correlation,
    start_trace_span,
)
from ..observability.trajectory import utc_now
from ..transport.stream_events import (
    extract_reasoning_delta,
    extract_tool_call_chunks,
    extract_tool_requests_from_updates,
    extract_tool_results_from_updates,
    extract_visible_text_delta,
    map_custom_payload_to_event,
    sanitize_stream_metadata,
)
from .chat_streaming import checkpointer_lacks_async_support, stream_graph_chunks
from .thread_turn_lease import ThreadTurnLeaseLost, ThreadTurnLeaseManager

_INTERNAL_MESSAGE_STREAM_NODES = frozenset({"plan", "reflect"})
_TOOL_RESULT_FALLBACK_VISIBLE_PREFIX = "我先根据已拿到的工具结果给出一个保守整理："


class ChatStreamLifecycleMixin:
    async def _stream_graph_chunks(
        self,
        *,
        payload: Any,
        config: dict[str, Any],
        context: RequestContext,
        thread_id: str,
        user_id: str,
        kind: str,
        run_name: str,
        branch_meta: BranchMeta | None,
        trace_correlation: TraceCorrelation | None,
    ) -> AsyncIterator[dict[str, Any] | None]:
        with start_trace_span(
            name=run_name,
            settings=self.runtime.settings,
            trace_correlation=trace_correlation,
            span_id=trace_correlation.root_span_id if trace_correlation is not None else None,
            attributes=self._turn_span_attributes(
                thread_id=thread_id,
                user_id=user_id,
                root_thread_id=context.root_thread_id,
                kind=kind,
                branch_meta=branch_meta,
            ),
        ):
            async for chunk in stream_graph_chunks(
                graph=self.runtime.graph,
                checkpointer=getattr(self.runtime, 'checkpointer', None),
                settings=self.runtime.settings,
                payload=payload,
                config=config,
                context=context,
            ):
                yield chunk

    def _checkpointer_lacks_async_support(self) -> bool:
        return checkpointer_lacks_async_support(getattr(self.runtime, 'checkpointer', None))

    async def _stream_graph_chunks_until_lease_lost(
        self,
        *,
        payload: Any,
        config: dict[str, Any],
        context: RequestContext,
        thread_id: str,
        user_id: str,
        kind: str,
        run_name: str,
        branch_meta: BranchMeta | None,
        trace_correlation: TraceCorrelation | None,
        turn_lease: ThreadTurnLeaseManager,
    ) -> AsyncIterator[dict[str, Any] | None]:
        stream_queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue(maxsize=1)

        async def produce_chunks() -> None:
            try:
                async for chunk in self._stream_graph_chunks(
                    payload=payload,
                    config=config,
                    context=context,
                    thread_id=thread_id,
                    user_id=user_id,
                    kind=kind,
                    run_name=run_name,
                    branch_meta=branch_meta,
                    trace_correlation=trace_correlation,
                ):
                    await stream_queue.put(("chunk", chunk))
                await stream_queue.put(("done", None))
            except Exception as exc:  # noqa: BLE001
                await stream_queue.put(("error", exc))

        producer_task = asyncio.create_task(produce_chunks())
        pending_next: asyncio.Task[tuple[str, Any]] | None = asyncio.create_task(stream_queue.get())
        pending_lost: asyncio.Task[bool] | None = asyncio.create_task(
            asyncio.to_thread(turn_lease.wait_lost_or_closed)
        )
        try:
            while pending_next is not None:
                wait_for = {pending_next}
                if pending_lost is not None:
                    wait_for.add(pending_lost)
                done, _ = await asyncio.wait(wait_for, return_when=asyncio.FIRST_COMPLETED)
                if pending_lost is not None and pending_lost in done:
                    if turn_lease.lost:
                        error = turn_lease.lost_error or ThreadTurnLeaseLost(
                            f"Thread turn lock heartbeat was lost for thread {thread_id}."
                        )
                        raise error
                    pending_lost = None
                    continue
                if pending_next in done:
                    item_type, item = await pending_next
                    if item_type == "done":
                        pending_next = None
                        break
                    if item_type == "error":
                        pending_next = None
                        raise item
                    pending_next = asyncio.create_task(stream_queue.get())
                    yield item
        finally:
            if pending_next is not None and not pending_next.done():
                pending_next.cancel()
                with suppress(asyncio.CancelledError):
                    await pending_next
            if not producer_task.done():
                producer_task.cancel()
                with suppress(asyncio.CancelledError):
                    await producer_task
            if pending_lost is not None and not pending_lost.done():
                pending_lost.cancel()
                with suppress(asyncio.CancelledError):
                    await pending_lost

    @staticmethod
    def _is_internal_message_stream(metadata: dict[str, Any] | None) -> bool:
        node = str((metadata or {}).get('langgraph_node') or '').strip()
        return node in _INTERNAL_MESSAGE_STREAM_NODES

    @staticmethod
    def _is_tool_result_fallback_visible_delta(delta: str) -> bool:
        return delta.lstrip().startswith(_TOOL_RESULT_FALLBACK_VISIBLE_PREFIX)

    async def _astream_result(
        self,
        *,
        thread_id: str,
        user_id: str,
        payload: Any,
        run_name: str,
        kind: str,
        request_id: str | None = None,
        context_skill_hints: tuple[str, ...] | None = None,
    ) -> AsyncIterator[str]:
        visible_text_buffer = ''
        reasoning_buffer = ''
        turn_lease: ThreadTurnLeaseManager | None = None
        context: RequestContext | None = None
        branch_meta: BranchMeta | None = None
        trace_correlation: TraceCorrelation | None = None
        initial_message_count = 0
        initial_llm_calls = 0
        input_messages = list(payload.get('messages', []) if isinstance(payload, dict) else [])
        started_at = utc_now()
        emit_closed_frame = True
        pending_branch_name_refresh: dict[str, Any] | None = None
        try:
            context, branch_meta, initial_values = self._preflight_thread_access(
                thread_id=thread_id,
                user_id=user_id,
                explicit_skill_hints=context_skill_hints,
            )
            initial_messages = list(initial_values.get('messages', []) or [])
            initial_message_count = len(initial_messages)
            initial_llm_calls = int(initial_values.get('llm_calls') or 0)
            turn_lease = self._thread_turn_lease(thread_id=thread_id)
            turn_lease.acquire()
            trace_correlation = build_trace_correlation(
                settings=self.runtime.settings,
                request_id=request_id,
            )
            config = build_invoke_config(
                settings=self.runtime.settings,
                thread_id=thread_id,
                user_id=user_id,
                root_thread_id=context.root_thread_id,
                branch_meta=branch_meta,
                trace_correlation=trace_correlation,
                run_name=run_name,
            )

            yield self._sse_frame(
                event='turn.status',
                data={'phase': 'accepted', 'thread_id': thread_id, 'kind': kind},
            )
            draft_message = self._draft_message_from_payload(payload)
            usage_before = self._context_usage_payload(initial_values, draft_message=draft_message)
            if (
                bool(getattr(self.runtime.settings, "context_auto_compaction_enabled", True))
                and float(usage_before.get("used_ratio") or 0)
                >= float(getattr(self.runtime.settings, "context_auto_compaction_pre_send_ratio", 0.92))
            ):
                yield self._sse_frame(
                    event='context.compaction.started',
                    data={'thread_id': thread_id, 'trigger': 'auto_pre_send', 'context_usage': usage_before},
                )
                compacted = self._auto_compact_context_before_turn(
                    thread_id=thread_id,
                    values=initial_values,
                    draft_message=draft_message,
                )
                latest_values = self._safe_get_values(thread_id) if compacted else initial_values
                yield self._sse_frame(
                    event='context.compaction.completed',
                    data={
                        'thread_id': thread_id,
                        'trigger': 'auto_pre_send',
                        'compacted': bool(compacted),
                        'context_usage': self._context_usage_payload(latest_values, draft_message=draft_message),
                    },
                )
            yield self._sse_frame(
                event='turn.status',
                data={'phase': 'invoke_started', 'thread_id': thread_id},
            )
            async for chunk in self._stream_graph_chunks_until_lease_lost(
                payload=payload,
                config=config,
                context=context,
                thread_id=thread_id,
                user_id=user_id,
                kind=kind,
                run_name=run_name,
                branch_meta=branch_meta,
                trace_correlation=trace_correlation,
                turn_lease=turn_lease,
            ):
                if chunk is None:
                    yield self._sse_frame(
                        event='status',
                        data={'stage': 'heartbeat', 'thread_id': thread_id, 'channel': 'system'},
                    )
                    continue
                chunk_type = chunk.get('type')
                data = chunk.get('data')
                namespace = list(chunk.get('ns') or ())
                chunk_metadata = sanitize_stream_metadata(chunk.get('metadata'))
                event_context = {'namespace': namespace}
                if chunk_metadata:
                    event_context['metadata'] = chunk_metadata

                if chunk_type == 'messages':
                    message_chunk, metadata = data
                    safe_metadata = sanitize_stream_metadata(metadata)
                    is_internal_message_stream = self._is_internal_message_stream(safe_metadata)
                    tool_chunks = extract_tool_call_chunks(message_chunk)

                    visible_delta = extract_visible_text_delta(message_chunk)
                    should_hide_visible_delta = (
                        is_internal_message_stream
                        or bool(tool_chunks)
                        or self._is_tool_result_fallback_visible_delta(visible_delta)
                    )
                    if visible_delta and not should_hide_visible_delta:
                        visible_text_buffer += visible_delta
                        payload_data = {
                            'delta': visible_delta,
                            'namespace': namespace,
                            'metadata': safe_metadata,
                            'channel': 'visible_text',
                        }
                        yield self._sse_frame(event='visible_text.delta', data=payload_data)
                        yield self._sse_frame(event='message.delta', data=payload_data)

                    reasoning_delta = extract_reasoning_delta(message_chunk)
                    if reasoning_delta and not is_internal_message_stream:
                        reasoning_buffer += reasoning_delta
                        yield self._sse_frame(
                            event='reasoning.delta',
                            data={
                                'delta': reasoning_delta,
                                'namespace': namespace,
                                'metadata': safe_metadata,
                                'channel': 'reasoning_tool_call',
                            },
                        )

                    for tool_chunk in tool_chunks:
                        yield self._sse_frame(
                            event='tool_call.delta',
                            data={
                                **tool_chunk,
                                'namespace': namespace,
                                'metadata': safe_metadata,
                                'channel': 'reasoning_tool_call',
                            },
                        )
                        yield self._sse_frame(
                            event='tool.call.delta',
                            data={
                                **tool_chunk,
                                'namespace': namespace,
                                'metadata': safe_metadata,
                                'channel': 'reasoning_tool_call',
                            },
                        )
                    continue

                if chunk_type == 'custom':
                    event_name, payload_data = map_custom_payload_to_event(data)
                    yield self._sse_frame(event=event_name, data={**payload_data, **event_context})
                    continue

                if chunk_type == 'updates':
                    for item in extract_tool_requests_from_updates(data):
                        yield self._sse_frame(event='tool.requested', data={**item, **event_context})
                    for item in extract_tool_results_from_updates(data):
                        yield self._sse_frame(event='tool.result', data={**item, **event_context})
                    yield self._sse_frame(
                        event='agent.update',
                        data={**event_context, 'data': data},
                    )
                    continue

                if chunk_type == 'tasks':
                    event_name = 'task.update'
                    payload_data: dict[str, Any]
                    if isinstance(data, dict):
                        event_key = str(data.get('event') or data.get('status') or '').strip().lower()
                        if event_key:
                            suffix = event_key.replace('on_', '').replace('task_', '')
                            event_name = f'task.{suffix}'
                        payload_data = dict(data)
                    else:
                        payload_data = {'value': data}
                    yield self._sse_frame(event=event_name, data={**payload_data, **event_context})
                    continue

                yield self._sse_frame(
                    event='stream.chunk',
                    data={'type': chunk_type, 'namespace': namespace, 'data': data},
                )

            turn_lease.raise_if_lost()
            latest_context, latest_branch_meta, final_values = self._context_for_thread(
                thread_id=thread_id,
                user_id=user_id,
            )
            final_state = self._response_payload(
                thread_id=thread_id,
                user_id=user_id,
                context=latest_context,
                branch_meta=latest_branch_meta,
                interrupts=self._safe_get_interrupts(thread_id),
                trace_correlation=trace_correlation,
            )
            turn_lease.raise_if_lost()
            final_messages = list(final_values.get('messages', []) or [])
            appended_messages = (
                final_messages[initial_message_count:]
                if len(final_messages) >= initial_message_count
                else final_messages
            )
            final_visible_text = self._latest_final_ai_text(appended_messages) or visible_text_buffer
            if final_visible_text:
                yield self._sse_frame(
                    event='visible_text.completed',
                    data={
                        'content': final_visible_text,
                        'thread_id': thread_id,
                    },
                )
                yield self._sse_frame(
                    event='message.completed',
                    data={
                        'content': final_visible_text,
                        'thread_id': thread_id,
                    },
                )
            if reasoning_buffer:
                yield self._sse_frame(
                    event='reasoning.completed',
                    data={
                        'content': reasoning_buffer,
                        'thread_id': thread_id,
                    },
                )
            turn_lease.raise_if_lost()
            self._record_turn_trajectory_best_effort(
                thread_id=thread_id,
                user_id=user_id,
                root_thread_id=latest_context.root_thread_id,
                kind=kind,
                status='succeeded',
                final_values=final_values,
                initial_message_count=initial_message_count,
                initial_llm_calls=initial_llm_calls,
                started_at=started_at,
                finished_at=utc_now(),
                branch_meta=latest_branch_meta,
                trace_correlation=trace_correlation,
                input_messages=input_messages,
                answer=final_visible_text,
            )
            turn_lease.raise_if_lost()
            self._schedule_post_turn_context_compaction(
                thread_id=thread_id,
                user_id=user_id,
                kind=kind,
            )
            turn_lease.raise_if_lost()
            if final_state.get('interrupts'):
                for interrupt_payload in final_state['interrupts']:
                    yield self._sse_frame(
                        event='turn.interrupt',
                        data={'thread_id': thread_id, 'interrupt': interrupt_payload},
                    )
            turn_lease.raise_if_lost()
            pending_branch_name_refresh = {
                "thread_id": thread_id,
                "user_id": user_id,
                "branch_meta": latest_branch_meta,
                "kind": kind,
            }
            yield self._sse_frame(
                event='turn.completed',
                data={'thread_state': final_state},
            )
        except Exception as exc:  # noqa: BLE001
            if not isinstance(exc, ThreadTurnLeaseLost) and turn_lease is not None and context is not None:
                self._record_turn_trajectory_best_effort(
                    thread_id=thread_id,
                    user_id=user_id,
                    root_thread_id=context.root_thread_id,
                    kind=kind,
                    status='failed',
                    final_values=self._safe_get_values(thread_id),
                    initial_message_count=initial_message_count,
                    initial_llm_calls=initial_llm_calls,
                    started_at=started_at,
                    finished_at=utc_now(),
                    branch_meta=branch_meta,
                    trace_correlation=trace_correlation,
                    input_messages=input_messages,
                    answer=visible_text_buffer or None,
                    error=str(exc),
                )
            yield self._sse_frame(
                event='turn.failed',
                data={
                    'error': exc.__class__.__name__,
                    'message': str(exc),
                    'thread_id': thread_id,
                },
            )
        except GeneratorExit:
            emit_closed_frame = False
            raise
        finally:
            if turn_lease is not None:
                turn_lease.close()
            if pending_branch_name_refresh is not None:
                self._schedule_branch_name_refresh_after_first_turn(**pending_branch_name_refresh)
            if emit_closed_frame:
                yield self._sse_frame(event='turn.closed', data={'status': 'ok', 'thread_id': thread_id})
