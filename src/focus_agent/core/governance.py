from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
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


def new_branch_decision_id() -> str:
    return f"branch-decision-{uuid4().hex}"


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


class BranchDecisionAction(StrEnum):
    SPLIT = "split"
    CONCLUDE = "conclude"
    MERGE_CANDIDATE = "merge_candidate"
    CONTINUE_CURRENT = "continue_current"
    FORK_CHILD_BRANCH = "fork_child_branch"
    FORK_SIBLING_BRANCH = "fork_sibling_branch"


class BranchDecisionRecommendationTarget(StrEnum):
    CONTINUE_CURRENT = "continue_current"
    FORK_CHILD_BRANCH = "fork_child_branch"
    FORK_SIBLING_BRANCH = "fork_sibling_branch"


class BranchDecisionStatus(StrEnum):
    SHADOWED = "shadowed"
    SUGGESTED = "suggested"
    PROMOTED = "promoted"
    DISMISSED = "dismissed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    ERROR = "error"


class BranchDecisionMode(StrEnum):
    SHADOW = "shadow"
    SUGGEST = "suggest"
    EXECUTE = "execute"


class BranchDecisionSignal(BaseModel):
    name: str
    value: Any = None
    score: float = 0.0
    weight: float = 0.0
    evidence_refs: list[str] = Field(default_factory=list)
    rationale: str = ""


class BranchDecisionConfig(BaseModel):
    enabled: bool = False
    mode: BranchDecisionMode = BranchDecisionMode.SHADOW
    min_confidence: float = 0.70
    split_threshold: float = 0.65
    conclude_threshold: float = 0.70
    merge_candidate_threshold: float = 0.75
    rate_limit_per_hour: int = 3
    recommendation_enabled: bool = False
    recommendation_mode: BranchDecisionMode = BranchDecisionMode.SHADOW
    recommendation_min_confidence: float = 0.72


class BranchDecisionEvent(BaseModel):
    decision_id: str = Field(default_factory=new_branch_decision_id)
    user_id: str | None = None
    root_thread_id: str
    source_thread_id: str
    branch_id: str | None = None
    recommendation_target: BranchDecisionRecommendationTarget | None = None
    target_parent_thread_id: str | None = None
    suggested_branch_name: str | None = None
    confidence: float | None = None
    action: BranchDecisionAction
    status: BranchDecisionStatus = BranchDecisionStatus.SHADOWED
    mode: BranchDecisionMode = BranchDecisionMode.SHADOW
    score: float = 0.0
    threshold: float = 0.0
    signals: list[BranchDecisionSignal] = Field(default_factory=list)
    rationale: str = ""
    idempotency_key: str | None = None
    request_id: str | None = None
    trace_id: str | None = None
    promoted_action_id: str | None = None
    dismiss_reason: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)
    executed_at: str | None = None

    @property
    def can_promote(self) -> bool:
        return (
            self.action
            in {
                BranchDecisionAction.SPLIT,
                BranchDecisionAction.FORK_CHILD_BRANCH,
                BranchDecisionAction.FORK_SIBLING_BRANCH,
            }
            and self.status
            in {
                BranchDecisionStatus.SHADOWED,
                BranchDecisionStatus.SUGGESTED,
            }
            and not self.promoted_action_id
        )


class BranchDecisionSummary(BaseModel):
    latest_decision: BranchDecisionEvent | None = None
    actionable: bool = False
    pending_action_id: str | None = None
    dismissed_count: int = 0


__all__ = [
    "BranchDecisionAction",
    "BranchDecisionConfig",
    "BranchDecisionEvent",
    "BranchDecisionMode",
    "BranchDecisionRecommendationTarget",
    "BranchDecisionSignal",
    "BranchDecisionStatus",
    "BranchDecisionSummary",
    "ContextMemoryEvidence",
    "FeedbackEvent",
    "SkillPreference",
    "SkillSelectionEvent",
    "new_branch_decision_id",
    "new_context_evidence_id",
    "new_feedback_event_id",
    "new_skill_preference_id",
    "new_skill_selection_id",
]
