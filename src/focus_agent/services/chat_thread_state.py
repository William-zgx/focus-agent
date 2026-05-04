from __future__ import annotations

from typing import Any, Callable

from ..core.branching import BranchMeta
from ..core.request_context import RequestContext
from ..core.tool_protocol import looks_like_textual_tool_call_artifact
from ..model_registry import default_thinking_enabled, supports_thinking_mode
from ..observability.tracing import TraceCorrelation, build_invoke_config
from .branch_actions import normalize_branch_actions, serialize_branch_actions
from .chat_serialization import thread_state_messages


def latest_final_ai_text(messages: list[Any], *, message_content_to_text: Callable[[Any], str]) -> str | None:
    for message in reversed(messages):
        if message.__class__.__name__ == "AIMessage" and not getattr(message, 'tool_calls', None):
            text = message_content_to_text(getattr(message, 'content', ''))
            if looks_like_textual_tool_call_artifact(text):
                continue
            return text
    return None


def effective_thinking_mode(*, model_id: str, thinking_mode: Any, settings: Any) -> str:
    if not supports_thinking_mode(model_id, settings=settings):
        return ''
    normalized = str(thinking_mode or '').strip().lower()
    if normalized in {'enabled', 'disabled'}:
        return normalized
    return 'enabled' if default_thinking_enabled(model_id, settings=settings) else 'disabled'


def response_payload(
    *,
    thread_id: str,
    user_id: str,
    context: RequestContext,
    branch_meta: BranchMeta | None,
    interrupts: list[Any],
    values: dict[str, Any],
    settings: Any,
    context_usage: dict[str, Any],
    message_content_to_text: Callable[[Any], str],
    message_limit: int,
    trace_correlation: TraceCorrelation | None = None,
) -> dict[str, Any]:
    messages = values.get('messages', [])
    branch_actions = serialize_branch_actions(normalize_branch_actions(values.get('branch_actions')))
    selected_model = str(values.get('selected_model') or settings.model)
    selected_thinking_mode = effective_thinking_mode(
        model_id=selected_model,
        thinking_mode=values.get('selected_thinking_mode'),
        settings=settings,
    )
    assistant_message = latest_final_ai_text(list(messages), message_content_to_text=message_content_to_text)
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
        'messages': thread_state_messages(list(messages), limit=message_limit),
        'interrupts': [getattr(item, 'value', item) for item in interrupts],
        'branch_actions': branch_actions,
        'trace': build_invoke_config(
            settings=settings,
            thread_id=thread_id,
            user_id=user_id,
            root_thread_id=context.root_thread_id,
            branch_meta=branch_meta,
            trace_correlation=trace_correlation,
        ),
        'context_usage': context_usage,
    }
