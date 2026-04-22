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


class MemoryRecord(MemoryModel):
    memory_id: str
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
    fingerprint: str | None = None
    semantic_key: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


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


class MemoryExtractionResult(MemoryModel):
    records: list[MemoryWriteRequest] = Field(default_factory=list)
    skipped_reasons: list[str] = Field(default_factory=list)
    summary: str = ""
