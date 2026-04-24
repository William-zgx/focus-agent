from __future__ import annotations

from typing import Iterable

from pydantic import Field

from ..core.branching import BranchRecord, BranchStatus
from ..core.request_context import RequestContext
from ..core.types import FindingItem
from ..storage.namespaces import conversation_main_namespace
from .dedupe import has_textual_overlap, memory_semantic_key
from .models import (
    MemoryKind,
    MemoryModel,
    MemoryRecord,
    MemoryScope,
    MemoryVisibility,
    MemoryWriteRequest,
)


class MemoryPromotionCandidate(MemoryModel):
    candidate_id: str
    summary: str
    semantic_key: str
    source_branch_id: str
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float | None = None
    promotable: bool = True
    skip_reason: str | None = None


class MemorySemanticConflict(MemoryModel):
    candidate_id: str
    existing_memory_id: str
    semantic_key: str
    reason: str = "semantic_conflict"
    candidate_summary: str
    existing_summary: str


class MemoryCuratorDecision(MemoryModel):
    enabled: bool = False
    auto_promote: bool = False
    branch_id: str | None = None
    root_thread_id: str | None = None
    status: str = "disabled"
    candidates: list[MemoryPromotionCandidate] = Field(default_factory=list)
    conflicts: list[MemorySemanticConflict] = Field(default_factory=list)
    promoted_memory_ids: list[str] = Field(default_factory=list)
    skipped: list[dict[str, str]] = Field(default_factory=list)


class MemoryCurator:
    def __init__(self, *, store=None):
        self.store = store

    def evaluate_branch_promotion(
        self,
        *,
        branch_record: BranchRecord,
        findings: Iterable[object],
        context: RequestContext,
        auto_promote: bool,
    ) -> MemoryCuratorDecision:
        if branch_record.branch_status in {
            BranchStatus.DISCARDED,
            BranchStatus.CLOSED,
        }:
            return MemoryCuratorDecision(
                enabled=True,
                auto_promote=auto_promote,
                branch_id=branch_record.branch_id,
                root_thread_id=branch_record.root_thread_id,
                status="blocked",
                skipped=[{"reason": f"branch_status:{branch_record.branch_status.value}"}],
            )

        candidates = [
            self._candidate_from_finding(
                finding=self._coerce_finding_item(item),
                branch_record=branch_record,
                context=context,
                index=index,
            )
            for index, item in enumerate(findings)
        ]
        candidates = [item for item in candidates if item.promotable]
        conflicts = self._find_conflicts(candidates, root_thread_id=branch_record.root_thread_id)
        conflicted_ids = {item.candidate_id for item in conflicts}
        skipped = [
            {"candidate_id": candidate.candidate_id, "reason": candidate.skip_reason or "not_promotable"}
            for candidate in candidates
            if not candidate.promotable
        ]
        skipped.extend(
            {"candidate_id": candidate_id, "reason": "semantic_conflict"}
            for candidate_id in sorted(conflicted_ids)
        )
        promotable = [item for item in candidates if item.candidate_id not in conflicted_ids]
        status = "ready"
        if conflicts:
            status = "needs_review"
        if not promotable and not conflicts:
            status = "empty"
        return MemoryCuratorDecision(
            enabled=True,
            auto_promote=auto_promote,
            branch_id=branch_record.branch_id,
            root_thread_id=branch_record.root_thread_id,
            status=status,
            candidates=promotable,
            conflicts=conflicts,
            skipped=skipped,
        )

    def candidate_to_write_request(
        self,
        *,
        candidate: MemoryPromotionCandidate,
        branch_record: BranchRecord,
        context: RequestContext,
        tags: list[str] | None = None,
    ) -> MemoryWriteRequest:
        return MemoryWriteRequest(
            kind=MemoryKind.BRANCH_FINDING,
            scope=MemoryScope.ROOT_THREAD,
            visibility=MemoryVisibility.SHARED,
            namespace=conversation_main_namespace(branch_record.root_thread_id),
            content=candidate.summary,
            summary=candidate.summary,
            tags=list(tags or []),
            evidence_refs=list(candidate.evidence_refs),
            source_thread_id=context.parent_thread_id or context.root_thread_id,
            source_branch_id=branch_record.branch_id,
            root_thread_id=context.root_thread_id,
            user_id=context.user_id,
            confidence=candidate.confidence,
            promoted_to_main=True,
            semantic_key=candidate.semantic_key,
        )

    def _find_conflicts(
        self,
        candidates: list[MemoryPromotionCandidate],
        *,
        root_thread_id: str,
    ) -> list[MemorySemanticConflict]:
        if self.store is None:
            return []
        namespace = conversation_main_namespace(root_thread_id)
        conflicts: list[MemorySemanticConflict] = []
        for candidate in candidates:
            for existing in self._search_existing(namespace, candidate.summary):
                existing_key = existing.semantic_key or memory_semantic_key(existing)
                same_key_different_summary = (
                    existing_key == candidate.semantic_key
                    and _normalize(existing.summary or existing.content) != _normalize(candidate.summary)
                )
                overlapping_branch_finding = (
                    existing.kind == MemoryKind.BRANCH_FINDING
                    and has_textual_overlap(existing.summary or existing.content, candidate.summary)
                    and _normalize(existing.summary or existing.content) != _normalize(candidate.summary)
                )
                if same_key_different_summary or overlapping_branch_finding:
                    conflicts.append(
                        MemorySemanticConflict(
                            candidate_id=candidate.candidate_id,
                            existing_memory_id=existing.memory_id,
                            semantic_key=candidate.semantic_key,
                            candidate_summary=candidate.summary,
                            existing_summary=existing.summary or existing.content,
                        )
                    )
                    break
        return conflicts

    def _search_existing(self, namespace: tuple[str, ...], query: str) -> list[MemoryRecord]:
        try:
            raw_hits = self.store.search(namespace, query=query, limit=20) or []
        except Exception:  # noqa: BLE001
            return []
        records: list[MemoryRecord] = []
        for raw in raw_hits:
            key = str(getattr(raw, "key", "") or "")
            payload = getattr(raw, "value", raw)
            if not isinstance(payload, dict):
                continue
            try:
                records.append(
                    MemoryRecord.model_validate(
                        {
                            "memory_id": payload.get("memory_id") or key or "memory",
                            "kind": payload.get("kind") or payload.get("type") or "turn_summary",
                            "scope": payload.get("scope") or "root_thread",
                            "visibility": payload.get("visibility") or "shared",
                            "namespace": tuple(payload.get("namespace") or namespace),
                            "content": payload.get("content") or payload.get("summary") or "",
                            "summary": payload.get("summary") or payload.get("content") or "",
                            "tags": payload.get("tags", []),
                            "evidence_refs": payload.get("evidence_refs", []),
                            "source_thread_id": payload.get("source_thread_id"),
                            "source_branch_id": payload.get("source_branch_id") or payload.get("branch_id"),
                            "root_thread_id": payload.get("root_thread_id"),
                            "user_id": payload.get("user_id"),
                            "confidence": payload.get("confidence"),
                            "importance": payload.get("importance", 0.5),
                            "promoted_to_main": payload.get("promoted_to_main", False),
                            "fingerprint": payload.get("fingerprint"),
                            "semantic_key": payload.get("semantic_key"),
                            **({"created_at": payload["created_at"]} if payload.get("created_at") else {}),
                            **({"updated_at": payload["updated_at"]} if payload.get("updated_at") else {}),
                        }
                    )
                )
            except Exception:  # noqa: BLE001
                continue
        return records

    @staticmethod
    def _candidate_from_finding(
        *,
        finding: FindingItem,
        branch_record: BranchRecord,
        context: RequestContext,
        index: int,
    ) -> MemoryPromotionCandidate:
        request = MemoryWriteRequest(
            kind=MemoryKind.BRANCH_FINDING,
            scope=MemoryScope.BRANCH,
            visibility=MemoryVisibility.PROMOTABLE,
            namespace=("conversation", branch_record.root_thread_id, "branch", branch_record.branch_id, "local_memory"),
            content=finding.finding,
            summary=finding.finding,
            evidence_refs=finding.evidence_refs,
            source_thread_id=branch_record.child_thread_id,
            source_branch_id=branch_record.branch_id,
            root_thread_id=branch_record.root_thread_id,
            user_id=context.user_id,
            confidence=finding.confidence,
        )
        content = finding.finding.strip()
        return MemoryPromotionCandidate(
            candidate_id=f"{branch_record.branch_id}:{index}",
            summary=content,
            semantic_key=memory_semantic_key(request),
            source_branch_id=branch_record.branch_id,
            evidence_refs=list(finding.evidence_refs),
            confidence=finding.confidence,
            promotable=bool(content and finding.merge_importable),
            skip_reason=None if content and finding.merge_importable else "not_merge_importable",
        )

    @staticmethod
    def _coerce_finding_item(value: object) -> FindingItem:
        if isinstance(value, FindingItem):
            return value
        if isinstance(value, dict):
            return FindingItem.model_validate(value)
        return FindingItem(finding=str(value))


def _normalize(value: str) -> str:
    return " ".join((value or "").casefold().split())


__all__ = [
    "MemoryCurator",
    "MemoryCuratorDecision",
    "MemoryPromotionCandidate",
    "MemorySemanticConflict",
]
