from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def new_context_evidence_id() -> str:
    return f"context-evidence-{uuid4().hex}"


def new_skill_selection_id() -> str:
    return f"skill-selection-{uuid4().hex}"


def new_feedback_event_id() -> str:
    return f"feedback-{uuid4().hex}"


def new_skill_preference_id() -> str:
    return f"skill-preference-{uuid4().hex}"


class ContextMemoryEvidence(BaseModel):
    evidence_id: str = Field(default_factory=new_context_evidence_id)
    user_id: str | None = None
    thread_id: str | None = None
    turn_id: str | None = None
    source_kind: str = "context_explain"
    selected_memories: list[dict[str, Any]] = Field(default_factory=list)
    excluded_memories: list[dict[str, Any]] = Field(default_factory=list)
    compaction_summary: dict[str, Any] = Field(default_factory=dict)
    drift_report: dict[str, Any] = Field(default_factory=dict)
    artifact_refs: list[dict[str, Any]] = Field(default_factory=list)
    token_counting: dict[str, Any] = Field(default_factory=dict)
    risk_flags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_now_iso)

    @property
    def memory_ids(self) -> list[str]:
        ids: list[str] = []
        for item in [*self.selected_memories, *self.excluded_memories]:
            raw = item.get("memory_id") or item.get("id")
            if raw is None:
                continue
            memory_id = str(raw)
            if memory_id and memory_id not in ids:
                ids.append(memory_id)
        return ids


class SkillSelectionEvent(BaseModel):
    selection_id: str = Field(default_factory=new_skill_selection_id)
    user_id: str | None = None
    message_hash: str | None = None
    message_preview: str | None = None
    selection_source: str = "none"
    explicit_hints: list[str] = Field(default_factory=list)
    activated_skill_ids: list[str] = Field(default_factory=list)
    matched_triggers: list[str] = Field(default_factory=list)
    semantic_candidates: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float = 0.0
    rationale: str = ""
    semantic_enabled: bool = True
    semantic_threshold: float = 0.22
    feedback: str | None = None
    feedback_reason: str | None = None
    user_override: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)


class SkillPreference(BaseModel):
    preference_id: str = Field(default_factory=new_skill_preference_id)
    user_id: str
    skill_id: str
    state: str = "default"
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)


class FeedbackEvent(BaseModel):
    event_id: str = Field(default_factory=new_feedback_event_id)
    user_id: str | None = None
    source_kind: str
    source_id: str | None = None
    sentiment: str | None = None
    category: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_now_iso)


__all__ = [
    "ContextMemoryEvidence",
    "FeedbackEvent",
    "SkillPreference",
    "SkillSelectionEvent",
    "new_context_evidence_id",
    "new_feedback_event_id",
    "new_skill_preference_id",
    "new_skill_selection_id",
]
