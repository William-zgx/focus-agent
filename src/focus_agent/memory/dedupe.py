from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re

from .models import MemoryKind, MemoryRecord, MemoryWriteRequest


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


def memory_semantic_key(record: MemoryWriteRequest | MemoryRecord) -> str:
    payload = {
        "kind": record.kind.value,
        "anchor": _semantic_anchor(record),
        "gist": _normalize_semantic_text(record.summary or record.content),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def memory_resolution_key(record: MemoryWriteRequest | MemoryRecord) -> str:
    if record.kind == MemoryKind.USER_PREFERENCE:
        topic = user_preference_topic(record.summary or record.content)
        if topic:
            user_anchor = record.user_id or _namespace_anchor(record.namespace)
            return f"user_preference:{user_anchor}:{topic}"
    return record.semantic_key or memory_semantic_key(record)


def user_preference_topic(text: str) -> str | None:
    lowered = (text or "").casefold()
    if any(token in lowered for token in ("中文", "英文", "chinese", "english")):
        return "response_language"
    if "emoji" in lowered or "表情" in text:
        return "emoji_style"
    if any(token in lowered for token in ("简洁", "详细", "concise", "brief", "verbose", "detailed")):
        return "verbosity"
    if "请叫我" in text or "call me" in lowered:
        return "addressing"
    return None


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
    merged.semantic_key = memory_semantic_key(merged)
    merged.fingerprint = memory_fingerprint(merged)
    return merged


def has_textual_overlap(left: str, right: str, *, minimum_overlap: int = 2) -> bool:
    left_tokens = _overlap_tokens(left)
    right_tokens = _overlap_tokens(right)
    if not left_tokens or not right_tokens:
        return False
    return len(left_tokens & right_tokens) >= minimum_overlap


def _semantic_anchor(record: MemoryWriteRequest | MemoryRecord) -> str:
    if record.kind == MemoryKind.USER_PREFERENCE:
        return f"user:{record.user_id or _namespace_anchor(record.namespace)}"
    if record.kind == MemoryKind.USER_PROFILE:
        return f"user-profile:{record.user_id or _namespace_anchor(record.namespace)}"
    if record.kind == MemoryKind.PROJECT_FACT:
        return f"project:{_namespace_anchor(record.namespace)}"
    if record.kind == MemoryKind.BRANCH_FINDING:
        root_thread_id = record.root_thread_id or _namespace_anchor(record.namespace)
        return f"branch-finding:{root_thread_id}:{record.source_branch_id or ''}"
    if record.root_thread_id:
        return f"thread:{record.root_thread_id}"
    return _namespace_anchor(record.namespace)


def _namespace_anchor(namespace: tuple[str, ...]) -> str:
    return "/".join(namespace[:4]) if namespace else "global"


def _normalize_semantic_text(text: str) -> str:
    return " ".join((text or "").casefold().split())


def _overlap_tokens(text: str) -> set[str]:
    lowered = (text or "").casefold()
    tokens = {token for token in re.findall(r"[a-z0-9]{3,}", lowered) if token}
    cjk_sequences = re.findall(r"[\u4e00-\u9fff]+", text or "")
    for sequence in cjk_sequences:
        compact = "".join(sequence.split())
        if len(compact) <= 2:
            tokens.add(compact)
            continue
        tokens.update(compact[index : index + 2] for index in range(len(compact) - 1))
    return tokens
