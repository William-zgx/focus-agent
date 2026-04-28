from __future__ import annotations

from focus_agent.core.types import ConversationRecord
from focus_agent.engine.runtime import AppRuntime

from ..contracts import ConversationSummaryResponse
from .token_usage import _normalize_token_usage


def _conversation_response(record: ConversationRecord) -> ConversationSummaryResponse:
    return ConversationSummaryResponse(
        root_thread_id=record.root_thread_id,
        title=record.title,
        is_archived=record.is_archived,
        archived_at=record.archived_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
        token_usage=_normalize_token_usage(record.token_usage),
    )


def _list_or_bootstrap_conversations(*, runtime: AppRuntime, user_id: str) -> list[ConversationRecord]:
    conversations = runtime.repo.list_conversations(owner_user_id=user_id)
    if conversations:
        return conversations

    default_root_thread_id = f"{user_id}-main"
    runtime.repo.ensure_thread_owner(
        thread_id=default_root_thread_id,
        root_thread_id=default_root_thread_id,
        owner_user_id=user_id,
    )
    runtime.repo.create_conversation(
        ConversationRecord(
            root_thread_id=default_root_thread_id,
            owner_user_id=user_id,
            title="Main",
            title_pending_ai=True,
        )
    )
    return runtime.repo.list_conversations(owner_user_id=user_id)




__all__ = [
    "_conversation_response",
    "_list_or_bootstrap_conversations",
]
