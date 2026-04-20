from __future__ import annotations

import uuid
from typing import Any

from ..core.branching import ImportedConclusion
from ..core.request_context import RequestContext
from ..core.types import FindingItem
from ..storage.namespaces import (
    branch_local_memory_namespace,
    conversation_main_namespace,
    root_thread_episodic_namespace,
)
from .dedupe import memory_fingerprint, merge_duplicate_records
from .models import MemoryKind, MemoryRecord, MemoryScope, MemoryVisibility, MemoryWriteRequest
from .policy import MemoryPolicy


class MemoryWriter:
    def __init__(self, *, store=None, policy: MemoryPolicy | None = None):
        self.store = store
        self.policy = policy or MemoryPolicy()

    def write_records(self, records: list[MemoryWriteRequest]) -> list[str]:
        if self.store is None:
            return []
        keys: list[str] = []
        for record in records:
            key = str(uuid.uuid4())
            payload = record.model_dump(mode="json")
            payload["memory_id"] = key
            payload["fingerprint"] = memory_fingerprint(record)
            self.store.put(record.namespace, key, payload)
            keys.append(key)
        return keys

    def persist_records(
        self,
        records: list[MemoryWriteRequest],
        *,
        context: RequestContext,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        outcome: dict[str, Any] = {
            "prepared": len(records),
            "written": [],
            "merged": [],
            "skipped": [],
            "failed": [],
        }
        if self.store is None:
            outcome["failed"].append({"reason": "store_unavailable"})
            return outcome

        for record in records:
            if not self.policy.should_persist(record=record, context=context, state=state):
                outcome["skipped"].append({"summary": record.summary or record.content[:80], "reason": "policy"})
                continue
            try:
                action, key = self._upsert_record(record)
            except Exception as exc:  # noqa: BLE001
                outcome["failed"].append(
                    {"summary": record.summary or record.content[:80], "reason": str(exc)}
                )
                continue
            if action == "written":
                outcome["written"].append(key)
            elif action == "merged":
                outcome["merged"].append(key)
            else:
                outcome["skipped"].append({"summary": record.summary or record.content[:80], "reason": action})
        return outcome

    def write_turn_summary(self, *, context: RequestContext, summary: str) -> str | None:
        if not summary.strip():
            return None
        keys = self.write_records(
            [
                MemoryWriteRequest(
                    kind=MemoryKind.TURN_SUMMARY,
                    scope=MemoryScope.ROOT_THREAD,
                    visibility=MemoryVisibility.PRIVATE,
                    namespace=root_thread_episodic_namespace(context.root_thread_id),
                    content=summary,
                    summary=summary[:240],
                    root_thread_id=context.root_thread_id,
                    user_id=context.user_id,
                    source_thread_id=context.branch_id or context.root_thread_id,
                )
            ]
        )
        return keys[0] if keys else None

    def write_branch_findings(
        self,
        *,
        context: RequestContext,
        branch_name: str,
        findings: list[FindingItem],
    ) -> list[str]:
        if not context.branch_id:
            return []
        records = [
            MemoryWriteRequest(
                kind=MemoryKind.BRANCH_FINDING,
                scope=MemoryScope.BRANCH,
                visibility=MemoryVisibility.PROMOTABLE,
                namespace=branch_local_memory_namespace(context.root_thread_id, context.branch_id),
                content=item.finding,
                summary=item.finding,
                evidence_refs=item.evidence_refs,
                source_thread_id=context.branch_id,
                source_branch_id=context.branch_id,
                root_thread_id=context.root_thread_id,
                user_id=context.user_id,
                confidence=item.confidence,
                tags=[branch_name],
            )
            for item in findings
        ]
        return self.write_records(records)

    def write_imported_conclusion(self, *, context: RequestContext, imported: ImportedConclusion) -> str:
        keys = self.write_records(
            [
                MemoryWriteRequest(
                    kind=MemoryKind.IMPORTED_CONCLUSION,
                    scope=MemoryScope.ROOT_THREAD,
                    visibility=MemoryVisibility.SHARED,
                    namespace=conversation_main_namespace(context.root_thread_id),
                    content=imported.summary,
                    summary=imported.summary,
                    evidence_refs=imported.evidence_refs,
                    source_thread_id=context.parent_thread_id or context.root_thread_id,
                    source_branch_id=imported.branch_id,
                    root_thread_id=context.root_thread_id,
                    user_id=context.user_id,
                    tags=[imported.branch_name, imported.mode.value],
                    promoted_to_main=True,
                )
            ]
        )
        return keys[0]

    def promote_branch_findings(
        self,
        *,
        context: RequestContext,
        branch_id: str,
        findings: list[FindingItem],
    ) -> list[str]:
        records = [
            MemoryWriteRequest(
                kind=MemoryKind.BRANCH_FINDING,
                scope=MemoryScope.ROOT_THREAD,
                visibility=MemoryVisibility.SHARED,
                namespace=conversation_main_namespace(context.root_thread_id),
                content=item.finding,
                summary=item.finding,
                evidence_refs=item.evidence_refs,
                source_thread_id=context.parent_thread_id or context.root_thread_id,
                source_branch_id=branch_id,
                root_thread_id=context.root_thread_id,
                user_id=context.user_id,
                confidence=item.confidence,
                promoted_to_main=True,
            )
            for item in findings
        ]
        return self.write_records(records)

    def _upsert_record(self, record: MemoryWriteRequest) -> tuple[str, str]:
        existing = self._find_existing_record(record)
        if existing is None:
            key = str(uuid.uuid4())
            payload = record.model_dump(mode="json")
            payload["memory_id"] = key
            payload["fingerprint"] = memory_fingerprint(record)
            self.store.put(record.namespace, key, payload)
            return "written", key

        key, current = existing
        if self._is_possible_conflict(current, record) and not self._should_replace(current, record):
            return "possible_conflict", key

        merged = merge_duplicate_records(current, record)
        payload = merged.model_dump(mode="json")
        payload["memory_id"] = key
        self.store.put(record.namespace, key, payload)
        return "merged", key

    def _find_existing_record(self, record: MemoryWriteRequest) -> tuple[str, MemoryRecord] | None:
        if self.store is None:
            return None
        query = (record.summary or record.content).strip()
        raw_hits = self.store.search(record.namespace, query=query, limit=5) or []
        incoming_fp = memory_fingerprint(record)
        normalized_incoming = _normalize_text(record.summary or record.content)
        best_match: tuple[str, MemoryRecord] | None = None
        for raw in raw_hits:
            key = str(getattr(raw, "key", "") or "")
            payload = getattr(raw, "value", raw)
            if not isinstance(payload, dict):
                continue
            current = MemoryRecord.model_validate(
                {
                    "memory_id": payload.get("memory_id") or key,
                    "kind": payload.get("kind", "turn_summary"),
                    "scope": payload.get("scope", "root_thread"),
                    "visibility": payload.get("visibility", "private"),
                    "namespace": tuple(payload.get("namespace") or record.namespace),
                    "content": payload.get("content") or payload.get("summary") or "",
                    "summary": payload.get("summary") or payload.get("content") or "",
                    "tags": payload.get("tags", []),
                    "evidence_refs": payload.get("evidence_refs", []),
                    "source_thread_id": payload.get("source_thread_id"),
                    "source_branch_id": payload.get("source_branch_id"),
                    "root_thread_id": payload.get("root_thread_id"),
                    "user_id": payload.get("user_id"),
                    "confidence": payload.get("confidence"),
                    "importance": payload.get("importance", 0.5),
                    "promoted_to_main": payload.get("promoted_to_main", False),
                    "fingerprint": payload.get("fingerprint"),
                    **(
                        {"created_at": payload["created_at"]}
                        if payload.get("created_at") is not None
                        else {}
                    ),
                    **(
                        {"updated_at": payload["updated_at"]}
                        if payload.get("updated_at") is not None
                        else {}
                    ),
                }
            )
            existing_fp = current.fingerprint or memory_fingerprint(current)
            normalized_existing = _normalize_text(current.summary or current.content)
            if existing_fp == incoming_fp or (
                current.kind == record.kind
                and current.scope == record.scope
                and normalized_existing
                and normalized_existing == normalized_incoming
            ):
                return key or current.memory_id, current
            if best_match is None and current.kind == record.kind and current.scope == record.scope:
                best_match = (key or current.memory_id, current)
        return best_match

    def _is_possible_conflict(self, existing: MemoryRecord, incoming: MemoryWriteRequest) -> bool:
        if existing.kind != incoming.kind or existing.scope != incoming.scope:
            return False
        if existing.scope not in {MemoryScope.USER, MemoryScope.PROJECT}:
            return False
        return _normalize_text(existing.summary or existing.content) != _normalize_text(
            incoming.summary or incoming.content
        )

    def _should_replace(self, existing: MemoryRecord, incoming: MemoryWriteRequest) -> bool:
        existing_confidence = float(existing.confidence or 0.0)
        incoming_confidence = float(incoming.confidence or 0.0)
        return (
            incoming.importance > existing.importance
            or incoming_confidence > existing_confidence
            or "纠正" in incoming.content
            or "改成" in incoming.content
        )


def _normalize_text(text: str) -> str:
    return " ".join((text or "").casefold().split())
