from __future__ import annotations

from typing import Any

from focus_agent.core.repo_call import (
    REPO_METHOD_ERROR,
    REPO_METHOD_MISSING,
    has_repo_method,
    safe_repo_call,
)
from focus_agent.memory import MemoryAuditEvent, MemoryCandidate, MemoryRecord
from focus_agent.repositories.memory_repository import MemoryRepository

from ..contracts import (
    MemoryAuditEventResponse,
    MemoryCandidateResponse,
    MemoryRecordResponse,
    MemoryUsageEvidenceResponse,
)


def _dt(value: object) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)


def _value(value: object) -> str | None:
    if value is None:
        return None
    resolved = value.value if hasattr(value, "value") else value
    return str(resolved)


def _model_payload(value: object) -> dict[str, Any]:
    if has_repo_method(value, "model_dump"):
        return _without_embedding_vectors(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return _without_embedding_vectors(value)
    return {}


def _without_embedding_vectors(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in dict(payload).items()
        if str(key) not in {"embedding", "embedding_vector", "vector"}
    }


def _memory_record_response(
    record: MemoryRecord,
    *,
    repository: MemoryRepository | None = None,
) -> MemoryRecordResponse:
    payload_redacted = _value(record.status) == "forgotten" or record.deleted_at is not None
    embedding_metadata = _embedding_response_metadata(record, repository=repository)
    return MemoryRecordResponse(
        memory_id=record.memory_id,
        kind=_value(record.kind),
        scope=_value(record.scope),
        visibility=_value(record.visibility),
        status=_value(record.status),
        namespace=list(record.namespace),
        content="" if payload_redacted else record.content,
        summary="[forgotten]" if payload_redacted else record.summary,
        tags=list(record.tags),
        evidence_refs=list(record.evidence_refs),
        source_thread_id=record.source_thread_id,
        source_branch_id=record.source_branch_id,
        root_thread_id=record.root_thread_id,
        user_id=record.user_id,
        confidence=record.confidence,
        importance=record.importance,
        promoted_to_main=record.promoted_to_main,
        semantic_key=record.semantic_key,
        fingerprint=record.fingerprint,
        embedding_status=_value(getattr(record, "embedding_status", None))
        or _value(embedding_metadata.get("status")),
        embedding_model_id=_value(getattr(record, "embedding_model_id", None))
        or _value(embedding_metadata.get("model_id")),
        embedding_updated_at=_dt(getattr(record, "embedding_updated_at", None))
        or _dt(embedding_metadata.get("updated_at")),
        created_at=_dt(record.created_at),
        updated_at=_dt(record.updated_at),
        deleted_at=_dt(record.deleted_at),
        payload_redacted=payload_redacted,
    )


def _memory_usage_response(*, memory_id: str, evidence: object) -> MemoryUsageEvidenceResponse:
    selected = list(getattr(evidence, "selected_memories", []) or [])
    excluded = list(getattr(evidence, "excluded_memories", []) or [])
    usage = "unknown"
    if _memory_list_contains(selected, memory_id):
        usage = "selected"
    elif _memory_list_contains(excluded, memory_id):
        usage = "excluded"
    return MemoryUsageEvidenceResponse(
        evidence_id=str(getattr(evidence, "evidence_id", "")),
        user_id=getattr(evidence, "user_id", None),
        thread_id=getattr(evidence, "thread_id", None),
        turn_id=getattr(evidence, "turn_id", None),
        source_kind=str(getattr(evidence, "source_kind", "context_explain")),
        usage=usage,
        selected_memories=selected,
        excluded_memories=excluded,
        risk_flags=list(getattr(evidence, "risk_flags", []) or []),
        created_at=getattr(evidence, "created_at", None),
    )


def _memory_list_contains(items: list[dict[str, Any]], memory_id: str) -> bool:
    return any(str(item.get("memory_id") or item.get("id") or "") == memory_id for item in items)


def _embedding_response_metadata(
    record: MemoryRecord,
    *,
    repository: MemoryRepository | None,
) -> dict[str, object]:
    if repository is None:
        return {}
    memory_id = record.memory_id
    for name in (
        "get_embedding_metadata",
        "get_memory_embedding_metadata",
        "get_embedding",
        "get_memory_embedding",
        "get_memory_record_embedding",
        "find_memory_embedding",
    ):
        metadata = safe_repo_call(
            repository,
            name,
            memory_id=memory_id,
            fallback_args=(memory_id,),
            default_missing=REPO_METHOD_MISSING,
            default_error=REPO_METHOD_ERROR,
            except_errors=(Exception,),
        )
        if metadata is REPO_METHOD_MISSING:
            continue
        if metadata is REPO_METHOD_ERROR:
            return {}
        return _embedding_metadata_payload(metadata)
    list_metadata = safe_repo_call(
        repository,
        "list_embedding_metadata",
        namespace=record.namespace,
        limit=500,
        default_missing=[],
        default_error=REPO_METHOD_ERROR,
        except_errors=(Exception,),
    )
    if list_metadata is not REPO_METHOD_ERROR:
        try:
            for metadata in list_metadata:
                payload = _embedding_metadata_payload(metadata)
                if payload.get("memory_id") == memory_id:
                    return payload
        except Exception:
            return {}
    status = safe_repo_call(
        repository,
        "get_embedding_status",
        memory_id,
        default_missing=REPO_METHOD_MISSING,
        default_error=REPO_METHOD_ERROR,
        except_errors=(Exception,),
    )
    if status is REPO_METHOD_ERROR:
        return {}
    if status is REPO_METHOD_MISSING:
        return {}
    return {"status": status}


def _embedding_metadata_payload(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if isinstance(value, dict):
        payload = value
    else:
        payload = {
            "memory_id": getattr(value, "memory_id", None),
            "status": getattr(value, "status", None),
            "model": getattr(value, "model", None),
            "model_id": getattr(value, "model_id", None),
            "updated_at": getattr(value, "updated_at", None),
        }
    return {
        "memory_id": payload.get("memory_id"),
        "status": payload.get("embedding_status") or payload.get("status"),
        "model_id": payload.get("embedding_model_id")
        or payload.get("model_id")
        or payload.get("model"),
        "updated_at": payload.get("embedding_updated_at") or payload.get("updated_at"),
    }


def _audit_event_response(event: MemoryAuditEvent) -> MemoryAuditEventResponse:
    decision = event.decision.value if hasattr(event.decision, "value") else str(event.decision)
    return MemoryAuditEventResponse(
        event_id=event.event_id,
        action=event.action,
        decision=decision,
        memory_id=event.memory_id,
        candidate_id=event.candidate_id,
        actor=event.actor,
        reason=event.reason,
        namespace=list(event.namespace),
        user_id=event.user_id,
        root_thread_id=event.root_thread_id,
        source_thread_id=event.source_thread_id,
        source_branch_id=event.source_branch_id,
        request_id=event.request_id,
        data=dict(event.data),
        created_at=_dt(event.created_at),
    )


def _candidate_response(candidate: MemoryCandidate) -> MemoryCandidateResponse:
    return MemoryCandidateResponse(
        candidate_id=candidate.candidate_id,
        status=candidate.status,
        agent_id=candidate.agent_id,
        task_id=candidate.task_id,
        branch_id=candidate.branch_id,
        root_thread_id=candidate.root_thread_id,
        user_id=candidate.user_id,
        evidence_refs=list(candidate.evidence_refs),
        record=_model_payload(candidate.record),
        reason=candidate.reason,
        created_at=_dt(candidate.created_at),
        updated_at=_dt(candidate.updated_at),
    )


__all__ = [
    "_audit_event_response",
    "_candidate_response",
    "_dt",
    "_embedding_metadata_payload",
    "_embedding_response_metadata",
    "_memory_list_contains",
    "_memory_record_response",
    "_memory_usage_response",
    "_model_payload",
    "_value",
    "_without_embedding_vectors",
]
