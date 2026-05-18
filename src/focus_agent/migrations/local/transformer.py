from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence as CollectionsSequence
from collections.abc import Sequence
from datetime import UTC, datetime

from ...memory.dedupe import memory_fingerprint, memory_semantic_key
from ...memory.models import (
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
    MemoryVisibility,
)
from .loader import LocalStoreItemRecord

_LEGACY_MEMORY_KIND_ALIASES: dict[str, MemoryKind] = {
    **{item.value: item for item in MemoryKind},
    "promoted_branch_finding": MemoryKind.BRANCH_FINDING,
    "account_setting": MemoryKind.USER_PROFILE,
}


def _legacy_payload_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _legacy_payload_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, CollectionsSequence) and not isinstance(value, (bytes, bytearray)):
        return [text for item in value if (text := str(item).strip())]
    return [str(value).strip()]


def _legacy_payload_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().casefold() in {"1", "true", "yes", "y", "on"}


def _legacy_payload_float(value: object, *, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return min(1.0, max(0.0, parsed))


def _legacy_payload_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    text = _legacy_payload_text(value)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _legacy_payload_enum(enum_type, value: object):
    text = _legacy_payload_text(value)
    if text is None:
        return None
    try:
        return enum_type(text)
    except ValueError:
        return None


def _legacy_memory_kind(payload: dict[str, object]) -> MemoryKind | None:
    raw_kind = _legacy_payload_text(payload.get("kind") or payload.get("type"))
    if raw_kind is None:
        return None
    return _LEGACY_MEMORY_KIND_ALIASES.get(raw_kind)


def _legacy_memory_scope(
    payload: dict[str, object],
    *,
    namespace: tuple[str, ...],
    kind: MemoryKind,
) -> MemoryScope:
    explicit = _legacy_payload_enum(MemoryScope, payload.get("scope"))
    if explicit is not None:
        return explicit

    if namespace[:1] == ("user",):
        return MemoryScope.USER
    if namespace[:1] == ("project",):
        return MemoryScope.PROJECT
    if namespace[:1] == ("skill",):
        return MemoryScope.SKILL
    if kind == MemoryKind.BRANCH_FINDING and _namespace_branch_id(namespace) is not None:
        return MemoryScope.BRANCH
    return MemoryScope.ROOT_THREAD


def _legacy_memory_visibility(
    payload: dict[str, object],
    *,
    namespace: tuple[str, ...],
    kind: MemoryKind,
) -> MemoryVisibility:
    explicit = _legacy_payload_enum(MemoryVisibility, payload.get("visibility"))
    if explicit is not None:
        return explicit

    payload_type = _legacy_payload_text(payload.get("type"))
    if payload_type == "promoted_branch_finding" or _legacy_payload_bool(payload.get("promoted_to_main")):
        return MemoryVisibility.SHARED
    if kind == MemoryKind.IMPORTED_CONCLUSION:
        return MemoryVisibility.SHARED
    if kind == MemoryKind.BRANCH_FINDING and _namespace_branch_id(namespace) is not None:
        return MemoryVisibility.PROMOTABLE
    return MemoryVisibility.PRIVATE


def _legacy_memory_id(item: LocalStoreItemRecord) -> str:
    explicit = _legacy_payload_text(item.value.get("memory_id"))
    if explicit is not None:
        return explicit
    seed = json.dumps(
        {"namespace": list(item.namespace), "key": item.key},
        ensure_ascii=False,
        sort_keys=True,
    )
    return f"legacy-langgraph-store:{hashlib.sha256(seed.encode('utf-8')).hexdigest()}"


def _namespace_root_thread_id(namespace: tuple[str, ...]) -> str | None:
    if len(namespace) >= 2 and namespace[0] == "conversation":
        return namespace[1]
    return None


def _namespace_branch_id(namespace: tuple[str, ...]) -> str | None:
    if len(namespace) >= 4 and namespace[0] == "conversation" and namespace[2] == "branch":
        return namespace[3]
    return None


def _namespace_user_id(namespace: tuple[str, ...]) -> str | None:
    if len(namespace) >= 2 and namespace[0] == "user":
        return namespace[1]
    return None


def _legacy_memory_content(payload: dict[str, object]) -> str | None:
    content = _legacy_payload_text(payload.get("content"))
    if content is not None:
        return content
    summary = _legacy_payload_text(payload.get("summary"))
    if summary is not None:
        return summary
    key_findings = _legacy_payload_list(payload.get("key_findings"))
    if key_findings:
        return "\n".join(key_findings)
    return None


def _focus_memory_record_from_store_item(
    item: LocalStoreItemRecord,
) -> tuple[MemoryRecord | None, str | None]:
    kind = _legacy_memory_kind(item.value)
    if kind is None:
        return None, "unrecognized_memory_kind"

    content = _legacy_memory_content(item.value)
    if content is None:
        return None, "missing_memory_content"

    created_at = (
        _legacy_payload_datetime(item.value.get("created_at"))
        or _legacy_payload_datetime(item.created_at)
        or datetime.fromtimestamp(0, tz=UTC)
    )
    updated_at = (
        _legacy_payload_datetime(item.value.get("updated_at"))
        or _legacy_payload_datetime(item.updated_at)
        or created_at
    )
    source_branch_id = (
        _legacy_payload_text(item.value.get("source_branch_id"))
        or _legacy_payload_text(item.value.get("branch_id"))
        or _namespace_branch_id(item.namespace)
    )
    payload_type = _legacy_payload_text(item.value.get("type"))

    record = MemoryRecord(
        memory_id=_legacy_memory_id(item),
        kind=kind,
        scope=_legacy_memory_scope(item.value, namespace=item.namespace, kind=kind),
        visibility=_legacy_memory_visibility(item.value, namespace=item.namespace, kind=kind),
        status=_legacy_payload_enum(MemoryStatus, item.value.get("status")) or MemoryStatus.ACTIVE,
        namespace=item.namespace,
        content=content,
        summary=_legacy_payload_text(item.value.get("summary")) or content[:240],
        tags=_legacy_payload_list(item.value.get("tags")),
        evidence_refs=_legacy_payload_list(item.value.get("evidence_refs")),
        source_thread_id=_legacy_payload_text(item.value.get("source_thread_id")),
        source_branch_id=source_branch_id,
        root_thread_id=_legacy_payload_text(item.value.get("root_thread_id"))
        or _namespace_root_thread_id(item.namespace),
        user_id=_legacy_payload_text(item.value.get("user_id")) or _namespace_user_id(item.namespace),
        confidence=_legacy_payload_float(item.value.get("confidence")),
        importance=_legacy_payload_float(item.value.get("importance"), default=0.5) or 0.5,
        promoted_to_main=(
            _legacy_payload_bool(item.value.get("promoted_to_main"))
            or payload_type in {"imported_conclusion", "promoted_branch_finding"}
        ),
        fingerprint=_legacy_payload_text(item.value.get("fingerprint")),
        semantic_key=_legacy_payload_text(item.value.get("semantic_key")),
        created_at=created_at,
        updated_at=updated_at,
        deleted_at=_legacy_payload_datetime(item.value.get("deleted_at")),
    )
    record.fingerprint = record.fingerprint or memory_fingerprint(record)
    record.semantic_key = record.semantic_key or memory_semantic_key(record)
    return record, None


def build_focus_memory_records(
    items: Sequence[LocalStoreItemRecord],
) -> tuple[list[MemoryRecord], list[dict[str, object]]]:
    records: list[MemoryRecord] = []
    skipped: list[dict[str, object]] = []
    for item in items:
        record, skip_reason = _focus_memory_record_from_store_item(item)
        if record is None:
            skipped.append(
                {
                    "namespace": list(item.namespace),
                    "key": item.key,
                    "reason": skip_reason or "unknown",
                }
            )
            continue
        records.append(record)
    return records, skipped


def _summarize_skip_reasons(skipped: Sequence[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in skipped:
        reason = str(item.get("reason") or "unknown")
        counts[reason] = counts.get(reason, 0) + 1
    return counts
