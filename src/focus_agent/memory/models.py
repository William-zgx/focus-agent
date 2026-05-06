from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MemoryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MemoryKind(str, Enum):
    USER_PREFERENCE = "user_preference"
    USER_PROFILE = "user_profile"
    PROJECT_FACT = "project_fact"
    TURN_SUMMARY = "turn_summary"
    BRANCH_FINDING = "branch_finding"
    IMPORTED_CONCLUSION = "imported_conclusion"
    ARTIFACT = "artifact"
    CITATION = "citation"
    TOOL_OBSERVATION = "tool_observation"


class MemoryScope(str, Enum):
    USER = "user"
    ROOT_THREAD = "root_thread"
    BRANCH = "branch"
    PROJECT = "project"
    SKILL = "skill"


class MemoryVisibility(str, Enum):
    PRIVATE = "private"
    PROMOTABLE = "promotable"
    SHARED = "shared"


class MemoryStatus(str, Enum):
    ACTIVE = "active"
    CONFLICT = "conflict"
    NEEDS_REVIEW = "needs_review"
    FORGOTTEN = "forgotten"
    DISCARDED = "discarded"


class MemoryWriteDecisionStatus(str, Enum):
    ACCEPTED = "accepted"
    MERGED = "merged"
    SKIPPED = "skipped"
    CONFLICT = "conflict"
    REQUIRES_REVIEW = "requires_review"
    FORGOTTEN = "forgotten"
    FAILED = "failed"


class MemoryRecord(MemoryModel):
    memory_id: str
    kind: MemoryKind
    scope: MemoryScope
    visibility: MemoryVisibility = MemoryVisibility.PRIVATE
    status: MemoryStatus = MemoryStatus.ACTIVE
    namespace: tuple[str, ...] = Field(default_factory=tuple)
    content: str
    summary: str = ""
    tags: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    source_thread_id: str | None = None
    source_branch_id: str | None = None
    root_thread_id: str | None = None
    user_id: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    promoted_to_main: bool = False
    fingerprint: str | None = None
    semantic_key: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    deleted_at: datetime | None = None


class MemorySearchHit(MemoryModel):
    record: MemoryRecord
    score: float = 0.0
    matched_terms: list[str] = Field(default_factory=list)
    namespace: tuple[str, ...] = Field(default_factory=tuple)
    rationale: str | None = None


class RetrievedMemoryBundle(MemoryModel):
    query: str
    hits: list[MemorySearchHit] = Field(default_factory=list)
    namespaces: list[tuple[str, ...]] = Field(default_factory=list)
    total_hits: int = 0
    retrieval_plan: dict[str, object] = Field(default_factory=dict)


class MemoryWriteRequest(MemoryModel):
    kind: MemoryKind
    scope: MemoryScope
    visibility: MemoryVisibility = MemoryVisibility.PRIVATE
    namespace: tuple[str, ...] = Field(default_factory=tuple)
    content: str
    summary: str = ""
    tags: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    source_thread_id: str | None = None
    source_branch_id: str | None = None
    root_thread_id: str | None = None
    user_id: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    promoted_to_main: bool = False
    semantic_key: str | None = None


class MemoryWriteDecision(MemoryModel):
    status: MemoryWriteDecisionStatus
    reason: str = ""
    memory_id: str | None = None
    audit_id: str | None = None
    tombstone_id: str | None = None
    action: str | None = None
    summary: str = ""
    redacted_payload: dict[str, object] = Field(default_factory=dict)


class MemoryAuditEvent(MemoryModel):
    event_id: str
    action: str
    decision: MemoryWriteDecisionStatus | str
    memory_id: str | None = None
    candidate_id: str | None = None
    actor: str | None = None
    reason: str | None = None
    namespace: tuple[str, ...] = Field(default_factory=tuple)
    user_id: str | None = None
    root_thread_id: str | None = None
    source_thread_id: str | None = None
    source_branch_id: str | None = None
    request_id: str | None = None
    data: dict[str, object] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utcnow)


class MemoryCandidate(MemoryModel):
    candidate_id: str
    status: str = "pending"
    agent_id: str | None = None
    task_id: str | None = None
    branch_id: str | None = None
    root_thread_id: str | None = None
    user_id: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    record: MemoryWriteRequest
    reason: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class MemoryRetrievalPlan(MemoryModel):
    query: str
    namespaces: list[tuple[str, ...]] = Field(default_factory=list)
    filters: dict[str, object] = Field(default_factory=dict)
    selected_memory_ids: list[str] = Field(default_factory=list)
    budget_reason: str = "top_k"
    source: str = "postgres"


class MemoryExtractionResult(MemoryModel):
    records: list[MemoryWriteRequest] = Field(default_factory=list)
    skipped_reasons: list[str] = Field(default_factory=list)
    summary: str = ""
