from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json

from .models import MemoryRecord, MemoryWriteRequest


def memory_fingerprint(record: MemoryWriteRequest | MemoryRecord) -> str:
    payload = {
        "kind": record.kind.value,
        "scope": record.scope.value,
        "visibility": record.visibility.value,
        "namespace": list(record.namespace),
        "content": record.content,
        "summary": record.summary,
        "tags": sorted(record.tags),
        "evidence_refs": sorted(record.evidence_refs),
        "source_thread_id": record.source_thread_id,
        "source_branch_id": record.source_branch_id,
        "root_thread_id": record.root_thread_id,
        "user_id": record.user_id,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def merge_duplicate_records(existing: MemoryRecord, incoming: MemoryWriteRequest) -> MemoryRecord:
    now = datetime.now(timezone.utc)
    merged = existing.model_copy(
        update={
            "content": incoming.content or existing.content,
            "summary": incoming.summary or existing.summary,
            "tags": sorted(set(existing.tags) | set(incoming.tags)),
            "evidence_refs": sorted(set(existing.evidence_refs) | set(incoming.evidence_refs)),
            "confidence": max(
                value for value in [existing.confidence, incoming.confidence] if value is not None
            )
            if existing.confidence is not None or incoming.confidence is not None
            else None,
            "importance": max(existing.importance, incoming.importance),
            "promoted_to_main": existing.promoted_to_main or incoming.promoted_to_main,
            "updated_at": now,
        }
    )
    merged.fingerprint = memory_fingerprint(merged)
    return merged
