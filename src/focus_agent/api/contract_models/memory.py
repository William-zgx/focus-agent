from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MemoryRecordResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    memory_id: str
    kind: str | None = None
    scope: str | None = None
    visibility: str | None = None
    status: str | None = None
    namespace: list[str] = Field(default_factory=list)
    content: str | None = None
    summary: str | None = None
    tags: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    source_thread_id: str | None = None
    source_branch_id: str | None = None
    root_thread_id: str | None = None
    user_id: str | None = None
    confidence: float | None = None
    importance: float | None = None
    promoted_to_main: bool | None = None
    semantic_key: str | None = None
    fingerprint: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    deleted_at: str | None = None
    payload_redacted: bool = False


class MemoryRecordListResponse(BaseModel):
    items: list[MemoryRecordResponse] = Field(default_factory=list)
    count: int = 0
    filters: dict[str, Any] = Field(default_factory=dict)
    limit: int = 50
    offset: int = 0
    backend: str = "postgres"
    available: bool = True
    error: str | None = None


class MemoryRecordDetailResponse(BaseModel):
    item: MemoryRecordResponse | None = None
    backend: str = "postgres"
    available: bool = True
    error: str | None = None


class ForgetMemoryRecordRequest(BaseModel):
    namespace: str | list[str] | None = None
    reason: str | None = None


class ForgetMemoryRecordResponse(BaseModel):
    memory_id: str
    forgotten: bool
    status: str | None = None
    tombstone_id: str | None = None
    audit_id: str | None = None
    decision: dict[str, Any] = Field(default_factory=dict)


class MemoryAuditEventResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    event_id: str
    action: str | None = None
    decision: str | None = None
    memory_id: str | None = None
    candidate_id: str | None = None
    actor: str | None = None
    reason: str | None = None
    namespace: list[str] = Field(default_factory=list)
    user_id: str | None = None
    root_thread_id: str | None = None
    source_thread_id: str | None = None
    source_branch_id: str | None = None
    request_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None


class MemoryAuditEventListResponse(BaseModel):
    items: list[MemoryAuditEventResponse] = Field(default_factory=list)
    count: int = 0
    filters: dict[str, Any] = Field(default_factory=dict)
    limit: int = 50
    backend: str = "postgres"
    available: bool = True
    error: str | None = None


class MemoryCandidateResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    candidate_id: str
    status: str | None = None
    agent_id: str | None = None
    task_id: str | None = None
    branch_id: str | None = None
    root_thread_id: str | None = None
    user_id: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    record: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class MemoryCandidateListResponse(BaseModel):
    items: list[MemoryCandidateResponse] = Field(default_factory=list)
    count: int = 0
    filters: dict[str, Any] = Field(default_factory=dict)
    limit: int = 50
    backend: str = "postgres"
    available: bool = True
    error: str | None = None


MemoryListResponse = MemoryRecordListResponse
MemoryDetailResponse = MemoryRecordDetailResponse
MemoryForgetRequest = ForgetMemoryRecordRequest
MemoryForgetResponse = ForgetMemoryRecordResponse
MemoryAuditListResponse = MemoryAuditEventListResponse


__all__ = [
    "MemoryAuditEventResponse",
    "MemoryAuditEventListResponse",
    "MemoryAuditListResponse",
    "MemoryCandidateListResponse",
    "MemoryCandidateResponse",
    "MemoryRecordDetailResponse",
    "MemoryRecordListResponse",
    "MemoryDetailResponse",
    "ForgetMemoryRecordRequest",
    "ForgetMemoryRecordResponse",
    "MemoryForgetRequest",
    "MemoryForgetResponse",
    "MemoryListResponse",
    "MemoryRecordResponse",
]
