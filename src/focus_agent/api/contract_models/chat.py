from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from focus_agent.core.branching import BranchActionProposal


class ChatTurnRequest(BaseModel):
    thread_id: str
    message: str
    model: str | None = None
    thinking_mode: str | None = None
    skill_hints: list[str] = Field(default_factory=list)
    user_id: str | None = None


class ModelOptionResponse(BaseModel):
    id: str
    provider: str
    provider_label: str
    provider_logo_slug: str | None = None
    provider_logo_letter: str | None = None
    name: str
    label: str
    is_default: bool = False
    supports_thinking: bool = False
    default_thinking_enabled: bool = False


class ModelCatalogResponse(BaseModel):
    default_model: str
    models: list[ModelOptionResponse] = Field(default_factory=list)


class ConversationSummaryResponse(BaseModel):
    root_thread_id: str
    title: str
    is_archived: bool = False
    archived_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    token_usage: dict[str, int] = Field(default_factory=dict)


class ConversationListResponse(BaseModel):
    conversations: list[ConversationSummaryResponse] = Field(default_factory=list)


class CreateConversationRequest(BaseModel):
    title: str | None = None


class UpdateConversationRequest(BaseModel):
    title: str


class ChatResumeRequest(BaseModel):
    thread_id: str
    resume: Any
    user_id: str | None = None


class ContextUsageResponse(BaseModel):
    used_tokens: int = 0
    token_limit: int = 0
    remaining_tokens: int = 0
    used_ratio: float = 0.0
    status: Literal["ok", "warm", "hot", "over", "compacting", "error"] = "ok"
    prompt_chars: int = 0
    prompt_budget_chars: int = 0
    tokenizer_mode: str = "chars_fallback"
    counting_backend: str = "chars_fallback"
    tokenizer_id: str | None = None
    estimated: bool = True
    drift_risk: str = "low"
    last_compacted_at: str | None = None


class ThreadContextPreviewRequest(BaseModel):
    draft_message: str | None = None


class ThreadContextPreviewResponse(BaseModel):
    context_usage: ContextUsageResponse


class ThreadContextCompactRequest(BaseModel):
    trigger: Literal["manual", "auto_pre_send", "auto_post_turn"] = "manual"


class ThreadStateResponse(BaseModel):
    thread_id: str
    root_thread_id: str
    assistant_message: str | None = None
    rolling_summary: str = ''
    selected_model: str = ''
    selected_thinking_mode: str = ''
    branch_meta: dict[str, Any] | None = None
    merge_proposal: dict[str, Any] | None = None
    merge_decision: dict[str, Any] | None = None
    merge_queue: list[dict[str, Any]] = Field(default_factory=list)
    active_skill_ids: list[str] = Field(default_factory=list)
    messages: list[dict[str, Any]] = Field(default_factory=list)
    interrupts: list[Any] = Field(default_factory=list)
    branch_actions: list[BranchActionProposal] = Field(default_factory=list)
    trace: dict[str, Any] = Field(default_factory=dict)
    context_usage: ContextUsageResponse | None = None


class ThreadContextCompactResponse(ThreadStateResponse):
    pass


__all__ = [
    "ChatTurnRequest",
    "ModelOptionResponse",
    "ModelCatalogResponse",
    "ConversationSummaryResponse",
    "ConversationListResponse",
    "CreateConversationRequest",
    "UpdateConversationRequest",
    "ChatResumeRequest",
    "ContextUsageResponse",
    "ThreadContextPreviewRequest",
    "ThreadContextPreviewResponse",
    "ThreadContextCompactRequest",
    "ThreadStateResponse",
    "ThreadContextCompactResponse",
]
