from __future__ import annotations

import asyncio
from contextlib import suppress
import json
from typing import Any, AsyncIterator

from langchain.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.types import Command
from pydantic import BaseModel
from pydantic import ValidationError

from ..core.branching import BranchMeta, BranchStatus
from ..core.request_context import RequestContext
from ..core.state import normalize_agent_state
from ..engine.runtime import AppRuntime
from ..model_registry import default_thinking_enabled, supports_thinking_mode
from ..observability.tracing import build_invoke_config
from ..skills.models import SkillSelection
from ..transport.stream_events import (
    extract_reasoning_delta,
    extract_visible_text_delta,
    extract_tool_call_chunks,
    extract_tool_requests_from_updates,
    extract_tool_results_from_updates,
    map_custom_payload_to_event,
    sanitize_stream_metadata,
)


class ChatService:
    def __init__(self, runtime: AppRuntime):
        self.runtime = runtime

    @staticmethod
    def _message_content_to_text(content: Any) -> str:
        if isinstance(content, list):
            return json.dumps(content, ensure_ascii=False)
        return str(content)

    def _serialize_message(self, message: Any) -> dict[str, Any]:
        return {
            'type': getattr(message, 'type', message.__class__.__name__.replace('Message', '').lower()),
            'content': self._message_content_to_text(getattr(message, 'content', '')),
            'tool_calls': getattr(message, 'tool_calls', None),
            'name': getattr(message, 'name', None),
            'id': getattr(message, 'id', None),
        }

    def _safe_snapshot(self, thread_id: str):
        try:
            return self.runtime.graph.get_state({'configurable': {'thread_id': thread_id}})
        except Exception:
            return None

    def _safe_get_values(self, thread_id: str) -> dict[str, Any]:
        snapshot = self._safe_snapshot(thread_id)
        values = normalize_agent_state(dict(getattr(snapshot, 'values', {}) or {})) if snapshot else normalize_agent_state()
        return self._backfill_import_records(thread_id=thread_id, values=values)

    def _safe_get_interrupts(self, thread_id: str) -> list[Any]:
        snapshot = self._safe_snapshot(thread_id)
        return list(getattr(snapshot, 'interrupts', []) or []) if snapshot else []

    @staticmethod
    def _imported_conclusion_message(imported: dict[str, Any]) -> str:
        summary = str(imported.get('summary') or '').strip()
        if not summary:
            return ''
        branch_name = str(imported.get('branch_name') or imported.get('branch_id') or 'unknown branch').strip()
        lines = [f"Imported conclusion from branch '{branch_name}':", summary]
        key_findings = [str(item).strip() for item in imported.get('key_findings', []) if str(item).strip()]
        if key_findings:
            lines.append('')
            lines.append('Key findings:')
            lines.extend(f"- {item}" for item in key_findings)
        evidence_refs = [str(item).strip() for item in imported.get('evidence_refs', []) if str(item).strip()]
        if evidence_refs:
            lines.append('')
            lines.append(f"Evidence refs: {', '.join(evidence_refs)}")
        return '\n'.join(lines).strip()

    @staticmethod
    def _append_imported_summary(existing_summary: Any, imported: dict[str, Any]) -> str:
        previous = str(existing_summary or '').strip()
        summary = str(imported.get('summary') or '').strip()
        if not summary:
            return previous
        branch_name = str(imported.get('branch_name') or imported.get('branch_id') or 'unknown branch').strip()
        imported_line = f"Imported from {branch_name}: {summary}"
        if imported_line in previous:
            return previous
        combined = '\n'.join(part for part in [previous, imported_line] if part)
        if len(combined) > 4000:
            combined = combined[-4000:]
        return combined

    def _backfill_import_records(self, *, thread_id: str, values: dict[str, Any]) -> dict[str, Any]:
        merge_queue = [item for item in values.get('merge_queue', []) if isinstance(item, dict)]
        if not merge_queue:
            return values

        messages = list(values.get('messages', []))
        existing_contents = {
            self._message_content_to_text(getattr(message, 'content', '')).strip()
            for message in messages
        }
        appended_messages: list[SystemMessage] = []
        updated_summary = values.get('rolling_summary', '')

        for imported in merge_queue:
            notice = self._imported_conclusion_message(imported)
            if notice and notice not in existing_contents:
                appended_messages.append(SystemMessage(content=notice))
                existing_contents.add(notice)
            updated_summary = self._append_imported_summary(updated_summary, imported)

        payload: dict[str, Any] = {}
        if appended_messages:
            payload['messages'] = appended_messages
            values = {**values, 'messages': messages + appended_messages}
        if updated_summary != values.get('rolling_summary', ''):
            payload['rolling_summary'] = updated_summary
            values = {**values, 'rolling_summary': updated_summary}

        if payload and hasattr(self.runtime.graph, 'update_state'):
            try:
                self.runtime.graph.update_state(
                    {'configurable': {'thread_id': thread_id}},
                    payload,
                    as_node='bootstrap_turn',
                )
            except Exception:
                pass

        return values

    def _branch_meta_from_repo(self, thread_id: str) -> BranchMeta | None:
        try:
            record = self.runtime.repo.get_by_child_thread_id(thread_id)
        except Exception:
            return None
        return BranchMeta(
            branch_id=record.branch_id,
            root_thread_id=record.root_thread_id,
            parent_thread_id=record.parent_thread_id,
            return_thread_id=record.return_thread_id,
            branch_name=record.branch_name,
            branch_role=record.branch_role,
            branch_depth=record.branch_depth,
            branch_status=record.branch_status,
            is_archived=record.is_archived,
            archived_at=record.archived_at,
            fork_checkpoint_id=record.fork_checkpoint_id,
            fork_strategy=record.fork_strategy,
        )

    def _branch_meta(self, *, thread_id: str, values: dict[str, Any]) -> BranchMeta | None:
        meta = values.get('branch_meta')
        if not meta:
            return self._branch_meta_from_repo(thread_id)
        try:
            return BranchMeta.model_validate(meta)
        except ValidationError:
            return self._branch_meta_from_repo(thread_id)

    def _context_for_thread(
        self,
        *,
        thread_id: str,
        user_id: str,
        explicit_skill_hints: tuple[str, ...] | None = None,
    ) -> tuple[RequestContext, BranchMeta | None, dict[str, Any]]:
        values = self._safe_get_values(thread_id)
        branch_meta = self._branch_meta(thread_id=thread_id, values=values)
        root_thread_id = branch_meta.root_thread_id if branch_meta else thread_id
        stored_skill_hints = tuple(str(item) for item in values.get('active_skill_ids', []) or ())
        context = RequestContext(
            user_id=user_id,
            root_thread_id=root_thread_id,
            branch_id=branch_meta.branch_id if branch_meta else None,
            parent_thread_id=branch_meta.parent_thread_id if branch_meta else None,
            branch_role=branch_meta.branch_role.value if branch_meta else None,
            skill_hints=explicit_skill_hints if explicit_skill_hints is not None else stored_skill_hints,
        )
        return context, branch_meta, values

    def _preflight_thread_access(
        self,
        *,
        thread_id: str,
        user_id: str,
        explicit_skill_hints: tuple[str, ...] | None = None,
        require_writable: bool = False,
    ) -> tuple[RequestContext, BranchMeta | None, dict[str, Any]]:
        context, branch_meta, values = self._context_for_thread(
            thread_id=thread_id,
            user_id=user_id,
            explicit_skill_hints=explicit_skill_hints,
        )
        self._ensure_access(thread_id=thread_id, user_id=user_id, context=context)
        if require_writable:
            self._ensure_thread_writable(branch_meta)
        return context, branch_meta, values

    def _ensure_access(self, *, thread_id: str, user_id: str, context: RequestContext) -> None:
        owner = self.runtime.repo.get_thread_owner(thread_id=thread_id)
        if owner is None:
            self.runtime.repo.ensure_thread_owner(
                thread_id=thread_id,
                root_thread_id=context.root_thread_id,
                owner_user_id=user_id,
            )
        else:
            self.runtime.repo.assert_thread_owner(thread_id=thread_id, owner_user_id=user_id)

    @staticmethod
    def _ensure_thread_writable(branch_meta: BranchMeta | None) -> None:
        if branch_meta and branch_meta.branch_status == BranchStatus.MERGED:
            raise PermissionError('Merged branches are read-only.')

    def _normalize_result(self, result: Any) -> tuple[dict[str, Any], list[Any]]:
        if hasattr(result, 'value') and hasattr(result, 'interrupts'):
            return dict(result.value or {}), list(result.interrupts or [])
        if isinstance(result, dict):
            return result, []
        return {'result': result}, []

    def _response_payload(
        self,
        *,
        thread_id: str,
        user_id: str,
        context: RequestContext,
        branch_meta: BranchMeta | None,
        interrupts: list[Any],
    ) -> dict[str, Any]:
        values = self._safe_get_values(thread_id)
        messages = values.get('messages', [])
        selected_model = str(values.get('selected_model') or self.runtime.settings.model)
        selected_thinking_mode = self._effective_thinking_mode(
            model_id=selected_model,
            thinking_mode=values.get('selected_thinking_mode'),
        )
        assistant_message: str | None = None
        for message in reversed(messages):
            if isinstance(message, AIMessage) and not getattr(message, 'tool_calls', None):
                assistant_message = self._message_content_to_text(message.content)
                break
        return {
            'thread_id': thread_id,
            'root_thread_id': context.root_thread_id,
            'assistant_message': assistant_message,
            'rolling_summary': values.get('rolling_summary', ''),
            'selected_model': selected_model,
            'selected_thinking_mode': selected_thinking_mode,
            'branch_meta': branch_meta.model_dump(mode='json') if branch_meta else None,
            'merge_proposal': values.get('merge_proposal'),
            'merge_decision': values.get('merge_decision'),
            'merge_queue': values.get('merge_queue', []),
            'active_skill_ids': values.get('active_skill_ids', []),
            'messages': [self._serialize_message(message) for message in messages[-20:]],
            'interrupts': [getattr(item, 'value', item) for item in interrupts],
            'trace': build_invoke_config(
                settings=self.runtime.settings,
                thread_id=thread_id,
                user_id=user_id,
                root_thread_id=context.root_thread_id,
                branch_meta=branch_meta,
            ),
        }

    @staticmethod
    def _effective_thinking_mode(*, model_id: str, thinking_mode: Any) -> str:
        normalized = str(thinking_mode or '').strip().lower()
        if normalized in {'enabled', 'disabled'}:
            return normalized
        if not supports_thinking_mode(model_id):
            return ''
        return 'enabled' if default_thinking_enabled(model_id) else 'disabled'

    def _run_invoke(
        self,
        *,
        thread_id: str,
        user_id: str,
        payload: Any,
        run_name: str,
        context_skill_hints: tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        context, branch_meta, _ = self._preflight_thread_access(
            thread_id=thread_id,
            user_id=user_id,
            explicit_skill_hints=context_skill_hints,
            require_writable=True,
        )
        config = build_invoke_config(
            settings=self.runtime.settings,
            thread_id=thread_id,
            user_id=user_id,
            root_thread_id=context.root_thread_id,
            branch_meta=branch_meta,
            run_name=run_name,
        )
        result = self.runtime.graph.invoke(
            payload,
            config=config,
            context=context,
            version='v2',
        )
        _, interrupts = self._normalize_result(result)
        return self._response_payload(
            thread_id=thread_id,
            user_id=user_id,
            context=context,
            branch_meta=branch_meta,
            interrupts=interrupts,
        )

    def send_message(
        self,
        *,
        thread_id: str,
        user_id: str,
        message: str,
        model: str | None = None,
        thinking_mode: str | None = None,
        skill_hints: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        selection = self._select_skills_for_message(
            message=message,
            explicit_skill_hints=skill_hints,
        )
        selected_model = model or self.runtime.settings.model
        payload: dict[str, Any] = {
            'messages': [HumanMessage(content=message)],
            'task_brief': selection.stripped_message or message,
            'active_skill_ids': list(selection.skill_ids),
            'selected_model': selected_model,
            'selected_thinking_mode': self._effective_thinking_mode(
                model_id=selected_model,
                thinking_mode=thinking_mode,
            ),
        }
        if selection.prompt_mode is not None:
            payload['prompt_mode'] = selection.prompt_mode
        return self._run_invoke(
            thread_id=thread_id,
            user_id=user_id,
            payload=payload,
            run_name='focus_agent_turn',
            context_skill_hints=selection.skill_ids,
        )

    def resume(self, *, thread_id: str, user_id: str, resume: Any) -> dict[str, Any]:
        return self._run_invoke(
            thread_id=thread_id,
            user_id=user_id,
            payload=Command(resume=resume),
            run_name='focus_agent_resume',
        )

    def get_thread_state(self, *, thread_id: str, user_id: str) -> dict[str, Any]:
        context, branch_meta, _ = self._context_for_thread(thread_id=thread_id, user_id=user_id)
        self._ensure_access(thread_id=thread_id, user_id=user_id, context=context)
        return self._response_payload(
            thread_id=thread_id,
            user_id=user_id,
            context=context,
            branch_meta=branch_meta,
            interrupts=self._safe_get_interrupts(thread_id),
        )

    def _select_skills_for_message(
        self,
        *,
        message: str,
        explicit_skill_hints: tuple[str, ...],
    ) -> SkillSelection:
        registry = getattr(self.runtime, 'skill_registry', None)
        if registry is None:
            return SkillSelection(
                skill_ids=tuple(str(item) for item in explicit_skill_hints),
                stripped_message=message.strip(),
            )
        return registry.select_for_message(
            message,
            explicit_hints=explicit_skill_hints,
        )

    @staticmethod
    def _json_safe(value: Any) -> Any:
        if isinstance(value, BaseModel):
            return value.model_dump(mode='json')
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, list):
            return [ChatService._json_safe(item) for item in value]
        if isinstance(value, tuple):
            return [ChatService._json_safe(item) for item in value]
        if isinstance(value, dict):
            return {str(key): ChatService._json_safe(item) for key, item in value.items()}
        if hasattr(value, 'content') or hasattr(value, 'tool_calls'):
            return {
                'type': getattr(value, 'type', value.__class__.__name__.replace('Message', '').lower()),
                'content': ChatService._message_content_to_text(getattr(value, 'content', '')),
                'tool_calls': ChatService._json_safe(getattr(value, 'tool_calls', None)),
                'name': getattr(value, 'name', None),
                'id': getattr(value, 'id', None),
            }
        return str(value)

    @staticmethod
    def _sse_frame(*, event: str, data: dict[str, Any]) -> str:
        payload = json.dumps(ChatService._json_safe(data), ensure_ascii=False)
        lines = [f'event: {event}']
        for line in payload.splitlines() or ['']:
            lines.append(f'data: {line}')
        return '\n'.join(lines) + '\n\n'

    def _schedule_branch_name_refresh_after_first_turn(
        self,
        *,
        thread_id: str,
        user_id: str,
        branch_meta: BranchMeta | None,
        kind: str,
    ) -> None:
        if kind != 'chat.turn':
            return
        if branch_meta is None:
            asyncio.create_task(
                asyncio.to_thread(
                    self.runtime.branch_service.refresh_conversation_title_after_first_turn,
                    root_thread_id=thread_id,
                    user_id=user_id,
                )
            )
            return
        asyncio.create_task(
            asyncio.to_thread(
                self.runtime.branch_service.refresh_branch_name_after_first_turn,
                child_thread_id=thread_id,
                user_id=user_id,
            )
        )

    async def _stream_graph_chunks(
        self,
        *,
        payload: Any,
        config: dict[str, Any],
        context: RequestContext,
    ) -> AsyncIterator[dict[str, Any] | None]:
        stream = self.runtime.graph.astream(
            payload,
            config=config,
            context=context,
            stream_mode=['messages', 'custom', 'updates', 'tasks'],
            version='v2',
        )
        stream_iter = stream.__aiter__()
        heartbeat_interval = max(float(self.runtime.settings.sse_heartbeat_seconds), 0.0)
        pending_next: asyncio.Task[Any] | None = None

        try:
            pending_next = asyncio.create_task(anext(stream_iter))
            while pending_next is not None:
                if heartbeat_interval > 0:
                    done, _ = await asyncio.wait({pending_next}, timeout=heartbeat_interval)
                    if not done:
                        yield None
                        continue
                try:
                    chunk = await pending_next
                except StopAsyncIteration:
                    pending_next = None
                    break
                pending_next = asyncio.create_task(anext(stream_iter))
                yield chunk
        finally:
            if pending_next is not None and not pending_next.done():
                pending_next.cancel()
                with suppress(asyncio.CancelledError):
                    await pending_next
            aclose = getattr(stream_iter, 'aclose', None)
            if callable(aclose):
                with suppress(Exception):  # noqa: BLE001
                    await aclose()

    async def _astream_result(
        self,
        *,
        thread_id: str,
        user_id: str,
        payload: Any,
        run_name: str,
        kind: str,
        context_skill_hints: tuple[str, ...] | None = None,
    ) -> AsyncIterator[str]:
        context, branch_meta, _ = self._preflight_thread_access(
            thread_id=thread_id,
            user_id=user_id,
            explicit_skill_hints=context_skill_hints,
        )
        config = build_invoke_config(
            settings=self.runtime.settings,
            thread_id=thread_id,
            user_id=user_id,
            root_thread_id=context.root_thread_id,
            branch_meta=branch_meta,
            run_name=run_name,
        )

        yield self._sse_frame(
            event='turn.status',
            data={'phase': 'accepted', 'thread_id': thread_id, 'kind': kind},
        )
        visible_text_buffer = ''
        reasoning_buffer = ''
        try:
            yield self._sse_frame(
                event='turn.status',
                data={'phase': 'invoke_started', 'thread_id': thread_id},
            )
            async for chunk in self._stream_graph_chunks(
                payload=payload,
                config=config,
                context=context,
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

                if chunk_type == 'messages':
                    message_chunk, metadata = data
                    safe_metadata = sanitize_stream_metadata(metadata)

                    visible_delta = extract_visible_text_delta(message_chunk)
                    if visible_delta:
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
                    if reasoning_delta:
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

                    for tool_chunk in extract_tool_call_chunks(message_chunk):
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
                    yield self._sse_frame(event=event_name, data={**payload_data, 'namespace': namespace})
                    continue

                if chunk_type == 'updates':
                    for item in extract_tool_requests_from_updates(data):
                        yield self._sse_frame(event='tool.requested', data={**item, 'namespace': namespace})
                    for item in extract_tool_results_from_updates(data):
                        yield self._sse_frame(event='tool.result', data={**item, 'namespace': namespace})
                    yield self._sse_frame(
                        event='agent.update',
                        data={'namespace': namespace, 'data': data},
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
                    yield self._sse_frame(event=event_name, data={**payload_data, 'namespace': namespace})
                    continue

                yield self._sse_frame(
                    event='stream.chunk',
                    data={'type': chunk_type, 'namespace': namespace, 'data': data},
                )

            latest_context, latest_branch_meta, _ = self._context_for_thread(thread_id=thread_id, user_id=user_id)
            final_state = self._response_payload(
                thread_id=thread_id,
                user_id=user_id,
                context=latest_context,
                branch_meta=latest_branch_meta,
                interrupts=self._safe_get_interrupts(thread_id),
            )
            final_visible_text = final_state.get('assistant_message') or visible_text_buffer
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
            if final_state.get('interrupts'):
                for interrupt_payload in final_state['interrupts']:
                    yield self._sse_frame(
                        event='turn.interrupt',
                        data={'thread_id': thread_id, 'interrupt': interrupt_payload},
                    )
            self._schedule_branch_name_refresh_after_first_turn(
                thread_id=thread_id,
                user_id=user_id,
                branch_meta=latest_branch_meta,
                kind=kind,
            )
            yield self._sse_frame(
                event='turn.completed',
                data={'thread_state': final_state},
            )
        except Exception as exc:  # noqa: BLE001
            yield self._sse_frame(
                event='turn.failed',
                data={
                    'error': exc.__class__.__name__,
                    'message': str(exc),
                    'thread_id': thread_id,
                },
            )
        finally:
            yield self._sse_frame(event='turn.closed', data={'status': 'ok', 'thread_id': thread_id})

    def stream_message(
        self,
        *,
        thread_id: str,
        user_id: str,
        message: str,
        model: str | None = None,
        thinking_mode: str | None = None,
        skill_hints: tuple[str, ...] = (),
    ) -> AsyncIterator[str]:
        selection = self._select_skills_for_message(
            message=message,
            explicit_skill_hints=skill_hints,
        )
        selected_model = model or self.runtime.settings.model
        payload: dict[str, Any] = {
            'messages': [HumanMessage(content=message)],
            'task_brief': selection.stripped_message or message,
            'active_skill_ids': list(selection.skill_ids),
            'selected_model': selected_model,
            'selected_thinking_mode': self._effective_thinking_mode(
                model_id=selected_model,
                thinking_mode=thinking_mode,
            ),
        }
        if selection.prompt_mode is not None:
            payload['prompt_mode'] = selection.prompt_mode
        self._preflight_thread_access(
            thread_id=thread_id,
            user_id=user_id,
            explicit_skill_hints=selection.skill_ids,
            require_writable=True,
        )
        return self._astream_result(
            thread_id=thread_id,
            user_id=user_id,
            payload=payload,
            run_name='focus_agent_turn',
            kind='chat.turn',
            context_skill_hints=selection.skill_ids,
        )

    def stream_resume(self, *, thread_id: str, user_id: str, resume: Any) -> AsyncIterator[str]:
        self._preflight_thread_access(
            thread_id=thread_id,
            user_id=user_id,
            require_writable=True,
        )
        return self._astream_result(
            thread_id=thread_id,
            user_id=user_id,
            payload=Command(resume=resume),
            run_name='focus_agent_resume',
            kind='chat.resume',
        )
