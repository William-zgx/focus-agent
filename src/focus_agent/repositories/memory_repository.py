from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from focus_agent.memory.models import (
    MemoryAuditEvent,
    MemoryCandidate,
    MemoryRecord,
    MemorySearchHit,
)


@dataclass(frozen=True, slots=True)
class MemoryListQuery:
    namespace: tuple[str, ...] | None = None
    kind: str | None = None
    scope: str | None = None
    visibility: str | None = None
    status: str | None = None
    user_id: str | None = None
    root_thread_id: str | None = None
    source_thread_id: str | None = None
    source_branch_id: str | None = None
    limit: int = 50
    offset: int = 0


class MemoryRepository(Protocol):
    def setup(self) -> None: ...

    def upsert_record(self, record: MemoryRecord) -> str: ...

    def find_existing(
        self,
        *,
        namespace: tuple[str, ...],
        fingerprint: str,
        semantic_key: str,
        kind: str | None = None,
        scope: str | None = None,
    ) -> MemoryRecord | None: ...

    def search(
        self,
        *,
        namespace: tuple[str, ...],
        query: str,
        limit: int,
    ) -> list[MemorySearchHit]: ...

    def list_records(self, query: MemoryListQuery) -> list[MemoryRecord]: ...

    def get_record(self, memory_id: str) -> MemoryRecord | None: ...

    def forget_record(
        self,
        *,
        memory_id: str,
        namespace: tuple[str, ...] | None = None,
        actor: str | None = None,
        reason: str | None = None,
    ) -> str | None: ...

    def append_audit_event(self, event: MemoryAuditEvent) -> str: ...

    def list_audit_events(
        self,
        *,
        memory_id: str | None = None,
        user_id: str | None = None,
        root_thread_id: str | None = None,
        source_thread_id: str | None = None,
        source_branch_id: str | None = None,
        limit: int = 50,
    ) -> list[MemoryAuditEvent]: ...

    def upsert_candidate(self, candidate: MemoryCandidate) -> str: ...

    def list_candidates(
        self,
        *,
        status: str | None = None,
        root_thread_id: str | None = None,
        user_id: str | None = None,
        branch_id: str | None = None,
        limit: int = 50,
    ) -> list[MemoryCandidate]: ...

    def update_candidate_status(
        self,
        *,
        candidate_id: str,
        status: str,
        reason: str | None = None,
    ) -> None: ...


__all__ = ["MemoryListQuery", "MemoryRepository"]
