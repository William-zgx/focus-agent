from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PromptMode(str, Enum):
    EXPLORE = "explore"
    EXECUTE = "execute"
    SYNTHESIZE = "synthesize"
    BRANCH_REVIEW = "branch_review"


class PinnedFact(StateModel):
    fact: str
    source: str | None = None
    pinned_by: str | None = None
    merge_importable: bool = True


class ConstraintItem(StateModel):
    constraint: str
    source: str = "user"
    rationale: str | None = None
    merge_importable: bool = True


class FindingItem(StateModel):
    finding: str
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source_branch_id: str | None = None
    merge_importable: bool = True


class ArtifactRef(StateModel):
    artifact_id: str | None = None
    title: str
    kind: str = "note"
    uri: str | None = None
    summary: str | None = None
    merge_importable: bool = True


class CitationRef(StateModel):
    label: str
    uri: str | None = None
    quote: str | None = None
    source_artifact_id: str | None = None


class ContextBudget(StateModel):
    recent_message_limit: int = Field(default=12, ge=1)
    findings_limit: int = Field(default=8, ge=0)
    artifact_limit: int = Field(default=6, ge=0)
    citation_limit: int = Field(default=10, ge=0)


class PlanStep(StateModel):
    id: str
    goal: str
    expected_tools: list[str] = Field(default_factory=list)
    done: bool = False
    note: str = ""


class Plan(StateModel):
    steps: list[PlanStep]
    success_criteria: str = ""
    created_at_call: int = 0
    replan_count: int = 0


class ReflectionVerdict(StateModel):
    status: Literal["done", "replan"]
    reasoning: str = ""
    missing: list[str] = Field(default_factory=list)


class ConversationRecord(StateModel):
    root_thread_id: str
    owner_user_id: str = "unknown"
    title: str
    title_pending_ai: bool = False
    is_archived: bool = False
    archived_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
