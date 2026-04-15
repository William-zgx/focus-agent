from __future__ import annotations

import uuid

from ..core.branching import ImportedConclusion
from ..core.request_context import RequestContext
from ..core.types import FindingItem
from ..storage.namespaces import (
    branch_local_memory_namespace,
    conversation_main_namespace,
    root_thread_episodic_namespace,
)
from .dedupe import memory_fingerprint
from .models import MemoryKind, MemoryScope, MemoryVisibility, MemoryWriteRequest
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
