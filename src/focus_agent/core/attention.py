from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AttentionCursor(BaseModel):
    version: Literal[1] = 1
    last_message_id: str | None = None
    seen_outcome_ids: list[str] = Field(default_factory=list, max_length=512)
    action_statuses: dict[str, str] = Field(default_factory=dict, max_length=512)
    reviewed_at: str | None = None


class AttentionReason(BaseModel):
    code: str
    source_ids: list[str] = Field(default_factory=list, max_length=16)


class AttentionPolicy(BaseModel):
    level: Literal["quiet", "notify", "ask"]
    reasons: list[AttentionReason] = Field(default_factory=list, max_length=32)


class AttentionItem(BaseModel):
    source_id: str
    kind: str
    status: str = ""
    text: str = Field(default="", max_length=800)
    previous_status: str | None = None


class AttentionEvidence(BaseModel):
    source_id: str
    kind: str
    thread_id: str
    action_id: str | None = None
    run_id: str | None = None


class CompletedOperation(BaseModel):
    outcome_id: str
    tool_call_id: str = ""
    tool_name: str
    status: str
    turn_id: str = ""
    operation_fingerprint: str | None = None
    operation_fingerprint_redacted_args: bool = False
    operation_id: str | None = None
    execution_version: str | None = None
    superseded_by: str | None = None
    cache_hit: bool = False
    deduplicated: bool = False


class ResumeExecution(BaseModel):
    version: str
    operation_id: str | None = None
    superseded_versions: list[str] = Field(default_factory=list, max_length=32)


class ResumePacket(BaseModel):
    goal: str = Field(default="", max_length=1200)
    decisions: list[AttentionItem] = Field(default_factory=list, max_length=32)
    open_items: list[AttentionItem] = Field(default_factory=list, max_length=32)
    next_action: AttentionItem | None = None
    evidence: list[AttentionEvidence] = Field(default_factory=list, max_length=64)
    completed_operations: list[CompletedOperation] = Field(default_factory=list, max_length=32)
    completed_operations_total: int = Field(default=0, ge=0)
    execution: ResumeExecution | None = None


class AttentionDiff(BaseModel):
    first_visit: bool
    frontier_missing: bool = False
    new_message_count: int = Field(default=0, ge=0)
    new_outcome_count: int = Field(default=0, ge=0)
    new_failed_outcome_count: int = Field(default=0, ge=0)
    action_transition_count: int = Field(default=0, ge=0)
    highlights: list[AttentionItem] = Field(default_factory=list, max_length=12)


class AttentionSnapshot(BaseModel):
    thread_id: str
    policy: AttentionPolicy
    resume: ResumePacket
    diff: AttentionDiff
    current_cursor: AttentionCursor


__all__ = [
    "AttentionCursor",
    "AttentionDiff",
    "AttentionEvidence",
    "AttentionItem",
    "AttentionPolicy",
    "AttentionReason",
    "AttentionSnapshot",
    "CompletedOperation",
    "ResumeExecution",
    "ResumePacket",
]
