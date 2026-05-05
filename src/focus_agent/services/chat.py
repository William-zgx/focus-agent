from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, AsyncIterator

from langchain.messages import AIMessage, HumanMessage
from langgraph.types import Command

from ..core.branching import BranchMeta
from ..core.request_context import RequestContext
from ..core.tool_protocol import looks_like_textual_tool_call_artifact
from ..engine.runtime import AppRuntime
from ..observability.tracing import (
    TraceCorrelation,
    build_invoke_config,
    build_trace_correlation,
    start_trace_span,
)
from ..observability.trajectory import utc_now
from ..skills.models import SkillSelection
from .chat_branch_action_facade import ChatBranchActionFacadeMixin
from .chat_serialization import (
    json_safe,
    message_content_to_text,
    serialize_message,
    sse_frame,
    thread_state_messages,
)
from .chat_compaction import ChatContextCompactionMixin
from .chat_stream_lifecycle import ChatStreamLifecycleMixin
from .chat_thread_state import effective_thinking_mode, response_payload
from .chat_thread_access import ChatThreadAccessMixin
from .chat_turn_errors import ConcurrentTurnError
from .chat_turn_recording import ChatTurnRecordingMixin


@dataclass(frozen=True)
class ChatServicePorts:
    settings: Any
    graph: Any
    repo: Any
    branch_service: Any | None = None
    skill_registry: Any | None = None
    trajectory_recorder: Any | None = None
    checkpointer: Any | None = None
    background_work: Any | None = None

    @classmethod
    def from_runtime(cls, runtime: Any) -> ChatServicePorts:
        return cls(
            settings=runtime.settings,
            graph=runtime.graph,
            repo=runtime.repo,
            branch_service=getattr(runtime, 'branch_service', None),
            skill_registry=getattr(runtime, 'skill_registry', None),
            trajectory_recorder=getattr(runtime, 'trajectory_recorder', None),
            checkpointer=getattr(runtime, 'checkpointer', None),
            background_work=getattr(runtime, 'background_work', None),
        )


class ChatService(
    ChatBranchActionFacadeMixin,
    ChatTurnRecordingMixin,
    ChatContextCompactionMixin,
    ChatStreamLifecycleMixin,
    ChatThreadAccessMixin,
):
    _THREAD_STATE_MESSAGE_LIMIT = 200
    _CONTEXT_COMPACTION_SUMMARY_CHARS = 2600
    _CONTEXT_COMPACTION_RECENT_MESSAGES = 8

    def __init__(self, runtime: AppRuntime | ChatServicePorts):
        self.ports = runtime if isinstance(runtime, ChatServicePorts) else ChatServicePorts.from_runtime(runtime)
        self.runtime = self.ports
        self._active_turns: set[str] = set()
        self._active_turns_lock = threading.Lock()
        self._background_work = self.ports.background_work

    def _acquire_thread_turn(self, *, thread_id: str) -> None:
        with self._active_turns_lock:
            if thread_id in self._active_turns:
                raise ConcurrentTurnError(
                    "This thread is still processing the previous turn. "
                    "Please wait for it to finish before sending another message."
                )
            self._active_turns.add(thread_id)

    def _release_thread_turn(self, *, thread_id: str) -> None:
        with self._active_turns_lock:
            self._active_turns.discard(thread_id)

    def _submit_background_work(self, *, key: str, func, delay_seconds: float = 0.0, **kwargs: Any) -> bool:
        if self._background_work is None:
            from .background_work import BoundedBackgroundQueue

            settings = self.runtime.settings
            self._background_work = BoundedBackgroundQueue(
                name="chat",
                max_concurrency=getattr(settings, "background_worker_max_concurrency", 2),
                max_size=getattr(settings, "background_queue_max_size", 1000),
            )
        return self._background_work.submit(
            key=key,
            func=func,
            delay_seconds=delay_seconds,
            **kwargs,
        )

    @staticmethod
    def _message_content_to_text(content: Any) -> str:
        return message_content_to_text(content)

    def _latest_final_ai_text(self, messages: list[Any]) -> str | None:
        for message in reversed(messages):
            if isinstance(message, AIMessage) and not getattr(message, 'tool_calls', None):
                text = self._message_content_to_text(message.content)
                if looks_like_textual_tool_call_artifact(text):
                    continue
                return text
        return None

    def _serialize_message(self, message: Any) -> dict[str, Any]:
        return serialize_message(message)

    def _thread_state_messages(self, messages: list[Any]) -> list[dict[str, Any]]:
        return thread_state_messages(messages, limit=self._THREAD_STATE_MESSAGE_LIMIT)

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
        trace_correlation: TraceCorrelation | None = None,
    ) -> dict[str, Any]:
        values = self._safe_get_values(thread_id)
        return response_payload(
            thread_id=thread_id,
            user_id=user_id,
            context=context,
            branch_meta=branch_meta,
            interrupts=interrupts,
            values=values,
            settings=self.runtime.settings,
            context_usage=self._context_usage_payload(values),
            message_content_to_text=self._message_content_to_text,
            message_limit=self._THREAD_STATE_MESSAGE_LIMIT,
            trace_correlation=trace_correlation,
        )

    def _effective_thinking_mode(self, *, model_id: str, thinking_mode: Any) -> str:
        return effective_thinking_mode(
            model_id=model_id,
            thinking_mode=thinking_mode,
            settings=self.runtime.settings,
        )

    def _turn_span_attributes(
        self,
        *,
        thread_id: str,
        user_id: str,
        root_thread_id: str,
        kind: str,
        branch_meta: BranchMeta | None,
    ) -> dict[str, Any]:
        attributes: dict[str, Any] = {
            "focus_agent.turn.kind": kind,
            "focus_agent.thread_id": thread_id,
            "focus_agent.root_thread_id": root_thread_id,
            "focus_agent.user_id": user_id,
            "service.name": getattr(self.runtime.settings, "tracing_service_name", "focus-agent"),
        }
        if branch_meta is not None:
            attributes.update(
                {
                    "focus_agent.branch_id": branch_meta.branch_id,
                    "focus_agent.branch_role": branch_meta.branch_role.value,
                    "focus_agent.branch_status": branch_meta.branch_status.value,
                }
            )
        return attributes

    def _run_invoke(
        self,
        *,
        thread_id: str,
        user_id: str,
        payload: Any,
        run_name: str,
        request_id: str | None = None,
        context_skill_hints: tuple[str, ...] | None = None,
        kind: str = 'chat.turn',
    ) -> dict[str, Any]:
        context, branch_meta, initial_values = self._preflight_thread_access(
            thread_id=thread_id,
            user_id=user_id,
            explicit_skill_hints=context_skill_hints,
            require_writable=True,
        )
        initial_message_count = len(list(initial_values.get('messages', []) or []))
        initial_llm_calls = int(initial_values.get('llm_calls') or 0)
        started_at = utc_now()
        trace_correlation: TraceCorrelation | None = None
        self._acquire_thread_turn(thread_id=thread_id)
        try:
            draft_message = self._draft_message_from_payload(payload)
            self._auto_compact_context_before_turn(
                thread_id=thread_id,
                values=initial_values,
                draft_message=draft_message,
            )
            trace_correlation = build_trace_correlation(
                settings=self.runtime.settings,
                request_id=request_id,
            )
            with start_trace_span(
                name=run_name,
                settings=self.runtime.settings,
                trace_correlation=trace_correlation,
                span_id=trace_correlation.root_span_id,
                attributes=self._turn_span_attributes(
                    thread_id=thread_id,
                    user_id=user_id,
                    root_thread_id=context.root_thread_id,
                    kind=kind,
                    branch_meta=branch_meta,
                ),
            ):
                config = build_invoke_config(
                    settings=self.runtime.settings,
                    thread_id=thread_id,
                    user_id=user_id,
                    root_thread_id=context.root_thread_id,
                    branch_meta=branch_meta,
                    trace_correlation=trace_correlation,
                    run_name=run_name,
                )
                result = self.runtime.graph.invoke(
                    payload,
                    config=config,
                    context=context,
                    version='v2',
                )
            _, interrupts = self._normalize_result(result)
            latest_context, latest_branch_meta, final_values = self._context_for_thread(thread_id=thread_id, user_id=user_id)
            response = self._response_payload(
                thread_id=thread_id,
                user_id=user_id,
                context=latest_context,
                branch_meta=latest_branch_meta,
                interrupts=interrupts,
                trace_correlation=trace_correlation,
            )
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
                input_messages=list(payload.get('messages', []) if isinstance(payload, dict) else []),
                answer=response.get('assistant_message'),
            )
            self._schedule_post_turn_context_compaction(
                thread_id=thread_id,
                user_id=user_id,
                kind=kind,
            )
            self._schedule_branch_name_refresh_after_first_turn(
                thread_id=thread_id,
                user_id=user_id,
                branch_meta=latest_branch_meta,
                kind=kind,
            )
            return response
        except Exception as exc:
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
                input_messages=list(payload.get('messages', []) if isinstance(payload, dict) else []),
                error=str(exc),
            )
            raise
        finally:
            self._release_thread_turn(thread_id=thread_id)

    def send_message(
        self,
        *,
        thread_id: str,
        user_id: str,
        message: str,
        model: str | None = None,
        thinking_mode: str | None = None,
        request_id: str | None = None,
        skill_hints: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        branch_action_result = self._handle_branch_action_turn(
            thread_id=thread_id,
            user_id=user_id,
            message=message,
            request_id=request_id,
        )
        if branch_action_result is not None:
            return branch_action_result["thread_state"]

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
            request_id=request_id,
            context_skill_hints=selection.skill_ids,
            kind='chat.turn',
        )

    def resume(self, *, thread_id: str, user_id: str, resume: Any, request_id: str | None = None) -> dict[str, Any]:
        return self._run_invoke(
            thread_id=thread_id,
            user_id=user_id,
            payload=Command(resume=resume),
            run_name='focus_agent_resume',
            request_id=request_id,
            kind='chat.resume',
        )

    def get_thread_state(self, *, thread_id: str, user_id: str, request_id: str | None = None) -> dict[str, Any]:
        context, branch_meta, _ = self._context_for_thread(thread_id=thread_id, user_id=user_id)
        self._ensure_access(thread_id=thread_id, user_id=user_id, context=context)
        trace_correlation = build_trace_correlation(
            settings=self.runtime.settings,
            request_id=request_id,
        )
        return self._response_payload(
            thread_id=thread_id,
            user_id=user_id,
            context=context,
            branch_meta=branch_meta,
            interrupts=self._safe_get_interrupts(thread_id),
            trace_correlation=trace_correlation,
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
        return json_safe(value)

    @staticmethod
    def _sse_frame(*, event: str, data: dict[str, Any]) -> str:
        return sse_frame(event=event, data=data)

    def stream_message(
        self,
        *,
        thread_id: str,
        user_id: str,
        message: str,
        model: str | None = None,
        thinking_mode: str | None = None,
        request_id: str | None = None,
        skill_hints: tuple[str, ...] = (),
    ) -> AsyncIterator[str]:
        context, branch_meta, values = self._context_for_thread(thread_id=thread_id, user_id=user_id)
        self._ensure_access(thread_id=thread_id, user_id=user_id, context=context)
        if self._branch_action_intent(values=values, branch_meta=branch_meta, message=message) is not None:
            return self._astream_branch_action_result(
                thread_id=thread_id,
                user_id=user_id,
                message=message,
                request_id=request_id,
            )

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
            request_id=request_id,
            context_skill_hints=selection.skill_ids,
        )

    def stream_resume(
        self,
        *,
        thread_id: str,
        user_id: str,
        resume: Any,
        request_id: str | None = None,
    ) -> AsyncIterator[str]:
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
            request_id=request_id,
        )
