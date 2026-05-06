from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any
from uuid import uuid4

from ..core.request_context import RequestContext
from ..repositories.memory_repository import MemoryRepository
from .dedupe import (
    has_textual_overlap,
    memory_fingerprint,
    memory_semantic_key,
    merge_duplicate_records,
    user_preference_topic,
)
from .models import (
    MemoryAuditEvent,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
    MemoryWriteDecision,
    MemoryWriteDecisionStatus,
    MemoryWriteRequest,
)
from .policy import MemoryPolicy


class MemoryService:
    def __init__(
        self,
        *,
        repository: MemoryRepository,
        policy: MemoryPolicy | None = None,
    ):
        self.repository = repository
        self.policy = policy or MemoryPolicy()

    def persist_records(
        self,
        records: list[MemoryWriteRequest],
        *,
        context: RequestContext,
        state: dict[str, Any],
        actor: str = "memory_pipeline",
    ) -> dict[str, Any]:
        outcome: dict[str, Any] = {
            "prepared": len(records),
            "written": [],
            "merged": [],
            "skipped": [],
            "failed": [],
            "decisions": [],
        }
        for record in records:
            if not self.policy.should_persist(record=record, context=context, state=state):
                decision = self._decision(
                    status=MemoryWriteDecisionStatus.SKIPPED,
                    action="policy",
                    reason="policy",
                    request=record,
                    actor=actor,
                )
                outcome["skipped"].append(
                    {"summary": record.summary or record.content[:80], "reason": "policy"}
                )
                outcome["decisions"].append(decision.model_dump(mode="json"))
                continue
            decision = self.upsert_request(
                record,
                actor=actor,
                reason="persist_records",
            )
            self._merge_decision_into_outcome(outcome, decision)
        return outcome

    def write_records(
        self,
        records: list[MemoryWriteRequest],
        *,
        actor: str = "memory_writer",
        reason: str = "direct_write",
    ) -> list[str]:
        ids: list[str] = []
        for record in records:
            decision = self.upsert_request(record, actor=actor, reason=reason)
            if decision.memory_id and decision.status in {
                MemoryWriteDecisionStatus.ACCEPTED,
                MemoryWriteDecisionStatus.MERGED,
            }:
                ids.append(decision.memory_id)
        return ids

    def upsert_request(
        self,
        request: MemoryWriteRequest,
        *,
        actor: str = "memory_service",
        reason: str = "upsert",
    ) -> MemoryWriteDecision:
        sanitized = _sanitize_request(request)
        record = _record_from_request(sanitized)
        existing = self.repository.find_existing(
            namespace=record.namespace,
            fingerprint=record.fingerprint or memory_fingerprint(record),
            semantic_key=record.semantic_key or memory_semantic_key(record),
            kind=record.kind.value,
            scope=record.scope.value,
        )
        if existing is None:
            self.repository.upsert_record(record)
            return self._decision(
                status=MemoryWriteDecisionStatus.ACCEPTED,
                action="written",
                reason=reason,
                request=sanitized,
                record=record,
                actor=actor,
            )

        if _is_possible_conflict(existing, sanitized) and not _should_replace(existing, sanitized):
            conflict = existing.model_copy(
                update={
                    "status": MemoryStatus.CONFLICT,
                    "updated_at": datetime.now(timezone.utc),
                }
            )
            self.repository.upsert_record(conflict)
            return self._decision(
                status=MemoryWriteDecisionStatus.CONFLICT,
                action="possible_conflict",
                reason="possible_conflict",
                request=sanitized,
                record=conflict,
                actor=actor,
            )

        merged = merge_duplicate_records(existing, sanitized)
        merged = merged.model_copy(update={"status": MemoryStatus.ACTIVE})
        self.repository.upsert_record(merged)
        return self._decision(
            status=MemoryWriteDecisionStatus.MERGED,
            action="merged",
            reason=reason,
            request=sanitized,
            record=merged,
            actor=actor,
        )

    def forget(
        self,
        *,
        memory_id: str,
        namespace: tuple[str, ...] | None = None,
        actor: str | None = None,
        reason: str | None = None,
    ) -> MemoryWriteDecision:
        existing = self.repository.get_record(memory_id)
        audit_namespace = namespace or (existing.namespace if existing else ())
        tombstone_id = self.repository.forget_record(
            memory_id=memory_id,
            namespace=namespace,
            actor=actor,
            reason=reason,
        )
        status = (
            MemoryWriteDecisionStatus.FORGOTTEN
            if tombstone_id is not None
            else MemoryWriteDecisionStatus.SKIPPED
        )
        audit = MemoryAuditEvent(
            event_id=str(uuid4()),
            action="forget",
            decision=status,
            memory_id=memory_id,
            actor=actor,
            reason=reason or ("forgotten" if tombstone_id else "not_found"),
            namespace=audit_namespace,
            user_id=existing.user_id if existing else None,
            root_thread_id=existing.root_thread_id if existing else None,
            source_thread_id=existing.source_thread_id if existing else None,
            source_branch_id=existing.source_branch_id if existing else None,
            data={"tombstone_id": tombstone_id} if tombstone_id else {},
        )
        audit_id = self.repository.append_audit_event(audit)
        return MemoryWriteDecision(
            status=status,
            reason=audit.reason or "",
            memory_id=memory_id,
            audit_id=audit_id,
            tombstone_id=tombstone_id,
            action="forget",
            redacted_payload={"tombstone_id": tombstone_id} if tombstone_id else {},
        )

    def _decision(
        self,
        *,
        status: MemoryWriteDecisionStatus,
        action: str,
        reason: str,
        request: MemoryWriteRequest,
        actor: str,
        record: MemoryRecord | None = None,
    ) -> MemoryWriteDecision:
        audit = MemoryAuditEvent(
            event_id=str(uuid4()),
            action=action,
            decision=status,
            memory_id=record.memory_id if record else None,
            actor=actor,
            reason=reason,
            namespace=request.namespace,
            user_id=request.user_id,
            root_thread_id=request.root_thread_id,
            source_thread_id=request.source_thread_id,
            source_branch_id=request.source_branch_id,
            data=_redacted_payload(request),
        )
        audit_id = self.repository.append_audit_event(audit)
        return MemoryWriteDecision(
            status=status,
            reason=reason,
            memory_id=record.memory_id if record else None,
            audit_id=audit_id,
            action=action,
            summary=request.summary or request.content[:120],
            redacted_payload=_redacted_payload(request),
        )

    @staticmethod
    def _merge_decision_into_outcome(outcome: dict[str, Any], decision: MemoryWriteDecision) -> None:
        if decision.status == MemoryWriteDecisionStatus.ACCEPTED:
            outcome["written"].append(decision.memory_id)
        elif decision.status == MemoryWriteDecisionStatus.MERGED:
            outcome["merged"].append(decision.memory_id)
        elif decision.status == MemoryWriteDecisionStatus.FAILED:
            outcome["failed"].append({"summary": decision.summary, "reason": decision.reason})
        else:
            outcome["skipped"].append({"summary": decision.summary, "reason": decision.reason})
        outcome["decisions"].append(decision.model_dump(mode="json"))


def _record_from_request(request: MemoryWriteRequest) -> MemoryRecord:
    now = datetime.now(timezone.utc)
    record = MemoryRecord(
        memory_id=str(uuid4()),
        kind=request.kind,
        scope=request.scope,
        visibility=request.visibility,
        status=MemoryStatus.ACTIVE,
        namespace=request.namespace,
        content=request.content,
        summary=request.summary or request.content[:240],
        tags=list(request.tags),
        evidence_refs=list(request.evidence_refs),
        source_thread_id=request.source_thread_id,
        source_branch_id=request.source_branch_id,
        root_thread_id=request.root_thread_id,
        user_id=request.user_id,
        confidence=request.confidence,
        importance=request.importance,
        promoted_to_main=request.promoted_to_main,
        created_at=now,
        updated_at=now,
    )
    record.fingerprint = memory_fingerprint(record)
    record.semantic_key = request.semantic_key or memory_semantic_key(record)
    return record


def _sanitize_request(request: MemoryWriteRequest) -> MemoryWriteRequest:
    content = _redact_sensitive_text(request.content)
    summary = _redact_sensitive_text(request.summary or request.content[:240])
    tags = sorted(set(request.tags) | ({"redacted"} if content != request.content or summary != (request.summary or request.content[:240]) else set()))
    return request.model_copy(update={"content": content, "summary": summary, "tags": tags})


def _redacted_payload(request: MemoryWriteRequest) -> dict[str, object]:
    return {
        "kind": request.kind.value,
        "scope": request.scope.value,
        "visibility": request.visibility.value,
        "namespace": list(request.namespace),
        "summary": _redact_sensitive_text(request.summary or request.content[:160]),
        "tags": list(request.tags),
        "evidence_refs": list(request.evidence_refs),
        "source_thread_id": request.source_thread_id,
        "source_branch_id": request.source_branch_id,
        "root_thread_id": request.root_thread_id,
        "user_id": request.user_id,
        "confidence": request.confidence,
        "importance": request.importance,
        "promoted_to_main": request.promoted_to_main,
    }


_SENSITIVE_PATTERNS = (
    re.compile(r"\b(sk-[A-Za-z0-9_-]{12,}|xox[baprs]-[A-Za-z0-9-]{10,})\b"),
    re.compile(r"(?i)\b(api[_ -]?key|token|secret|password)\s*[:=]\s*['\"]?[^'\"\s,;]+"),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
)


def _redact_sensitive_text(text: str) -> str:
    redacted = text or ""
    for pattern in _SENSITIVE_PATTERNS:
        redacted = pattern.sub("[redacted]", redacted)
    return redacted


def _is_possible_conflict(existing: MemoryRecord, incoming: MemoryWriteRequest) -> bool:
    if existing.kind != incoming.kind or existing.scope != incoming.scope:
        return False
    if existing.scope not in {MemoryScope.USER, MemoryScope.PROJECT}:
        return False
    return _normalize_text(existing.summary or existing.content) != _normalize_text(
        incoming.summary or incoming.content
    )


def _should_replace(existing: MemoryRecord, incoming: MemoryWriteRequest) -> bool:
    existing_confidence = float(existing.confidence or 0.0)
    incoming_confidence = float(incoming.confidence or 0.0)
    if (
        incoming.scope == MemoryScope.USER
        and user_preference_topic(existing.summary or existing.content)
        and user_preference_topic(existing.summary or existing.content)
        == user_preference_topic(incoming.summary or incoming.content)
    ):
        return True
    return (
        incoming.importance > existing.importance
        or incoming_confidence > existing_confidence
        or _has_correction_signal(incoming.summary or incoming.content)
        or has_textual_overlap(existing.summary or existing.content, incoming.summary or incoming.content)
    )


def _normalize_text(text: str) -> str:
    return " ".join((text or "").casefold().split())


def _has_correction_signal(text: str) -> bool:
    lowered = (text or "").casefold()
    return any(
        marker in lowered
        for marker in (
            "纠正",
            "更正",
            "修正",
            "改成",
            "改为",
            "更新为",
            "以此为准",
            "instead",
            "from now on",
            "correction",
            "corrected",
        )
    )


__all__ = ["MemoryService"]
