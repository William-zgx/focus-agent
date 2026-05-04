from __future__ import annotations

import uuid

from ..core.branching import BranchRecord, ImportedConclusion
from ..core.request_context import RequestContext
from ..core.types import FindingItem
from ..memory import MemoryCurator, MemoryWriter
from ..memory.models import MemoryKind, MemoryScope, MemoryVisibility, MemoryWriteRequest
from ..storage.namespaces import branch_namespace, conversation_main_namespace


class BranchMemoryPromotionMixin:
    """Memory persistence helpers used by branch merge workflows."""

    _last_memory_curator_decision: dict[str, object] | None

    def _persist_branch_findings_to_branch_memory(
        self,
        *,
        branch_record: BranchRecord,
        findings: list[object],
    ) -> list[str]:
        if self.store is None:
            return []
        context = self._build_branch_request_context(branch_record)
        memory_writer = getattr(self, "memory_writer", None)
        if memory_writer is not None:
            return memory_writer.write_branch_findings(
                context=context,
                branch_name=branch_record.branch_name,
                findings=[self._coerce_finding_item(finding) for finding in findings],
            )

        namespace = branch_namespace(branch_record.root_thread_id, branch_record.branch_id)
        keys: list[str] = []
        for finding in findings:
            item = self._coerce_finding_item(finding)
            key = str(uuid.uuid4())
            self.store.put(
                namespace,
                key,
                {
                    "type": "branch_finding",
                    "branch_id": branch_record.branch_id,
                    "branch_name": branch_record.branch_name,
                    "summary": item.finding,
                    "evidence_refs": item.evidence_refs,
                    "confidence": item.confidence,
                },
            )
            keys.append(key)
        return keys

    @staticmethod
    def _imported_conclusion_message(imported: ImportedConclusion) -> str:
        lines = [f"Imported conclusion from branch '{imported.branch_name}':", imported.summary.strip()]
        key_findings = [item.strip() for item in imported.key_findings if str(item).strip()]
        if key_findings:
            lines.append("")
            lines.append("Key findings:")
            lines.extend(f"- {item}" for item in key_findings)
        evidence_refs = [item.strip() for item in imported.evidence_refs if str(item).strip()]
        if evidence_refs:
            lines.append("")
            lines.append(f"Evidence refs: {', '.join(evidence_refs)}")
        return "\n".join(lines).strip()

    @staticmethod
    def _append_imported_summary(existing_summary: object, imported: ImportedConclusion) -> str:
        previous = str(existing_summary or "").strip()
        imported_line = f"Imported from {imported.branch_name}: {imported.summary.strip()}".strip()
        combined = "\n".join(part for part in [previous, imported_line] if part)
        if len(combined) > 4000:
            combined = combined[-4000:]
        return combined

    @classmethod
    def _filter_merge_importable_findings(cls, findings: list[object]) -> list[FindingItem]:
        promotable: list[FindingItem] = []
        for finding in findings:
            item = cls._coerce_finding_item(finding)
            if item.merge_importable:
                promotable.append(item)
        return promotable

    @staticmethod
    def _main_memory_audit_tags(
        *,
        branch_record: BranchRecord,
        memory_kind: str,
        extra_tags: list[str] | None = None,
    ) -> list[str]:
        tags = [
            "audit:branch_merge_promotion",
            "target:conversation_main",
            f"kind:{memory_kind}",
            f"branch:{branch_record.branch_id}",
            f"role:{branch_record.branch_role.value}",
        ]
        for tag in extra_tags or []:
            value = str(tag).strip()
            if value:
                tags.append(value)
        return tags

    def _write_imported_conclusion_to_main_memory(
        self,
        *,
        branch_record: BranchRecord,
        context: RequestContext,
        imported: ImportedConclusion,
    ) -> str | None:
        if self.store is None:
            return None
        namespace = conversation_main_namespace(branch_record.root_thread_id)
        tags = self._main_memory_audit_tags(
            branch_record=branch_record,
            memory_kind=MemoryKind.IMPORTED_CONCLUSION.value,
            extra_tags=[branch_record.branch_name, f"mode:{imported.mode.value}"],
        )
        source_thread_id = context.parent_thread_id or context.root_thread_id
        memory_writer = getattr(self, "memory_writer", None)
        if memory_writer is not None:
            records = [
                MemoryWriteRequest(
                    kind=MemoryKind.IMPORTED_CONCLUSION,
                    scope=MemoryScope.ROOT_THREAD,
                    visibility=MemoryVisibility.SHARED,
                    namespace=namespace,
                    content=imported.summary,
                    summary=imported.summary,
                    tags=tags,
                    evidence_refs=imported.evidence_refs,
                    source_thread_id=source_thread_id,
                    source_branch_id=imported.branch_id,
                    root_thread_id=context.root_thread_id,
                    user_id=context.user_id,
                    promoted_to_main=True,
                )
            ]
            keys = memory_writer.write_records(records)
            return keys[0] if keys else None

        key = str(uuid.uuid4())
        self.store.put(
            namespace,
            key,
            {
                "type": "imported_conclusion",
                "branch_id": imported.branch_id,
                "branch_name": imported.branch_name,
                "mode": imported.mode.value,
                "summary": imported.summary,
                "key_findings": imported.key_findings,
                "evidence_refs": imported.evidence_refs,
                "artifacts": imported.artifacts,
                "tags": tags,
                "promoted_to_main": True,
                "source_thread_id": source_thread_id,
                "source_branch_id": imported.branch_id,
                "root_thread_id": context.root_thread_id,
                "user_id": context.user_id,
            },
        )
        return key

    def promote_branch_findings_to_main_memory(
        self,
        *,
        branch_record: BranchRecord,
        findings: list[object],
        memory_context: RequestContext | None = None,
    ) -> list[str]:
        self._last_memory_curator_decision = None
        if self.store is None:
            return []
        promotable_findings = self._filter_merge_importable_findings(findings)
        if not promotable_findings:
            return []
        context = memory_context or self._build_branch_request_context(branch_record)
        namespace = conversation_main_namespace(branch_record.root_thread_id)
        tags = self._main_memory_audit_tags(
            branch_record=branch_record,
            memory_kind=MemoryKind.BRANCH_FINDING.value,
            extra_tags=[branch_record.branch_name, "filter:merge_importable"],
        )
        source_thread_id = context.parent_thread_id or context.root_thread_id
        memory_writer = getattr(self, "memory_writer", None)
        settings = getattr(self, "settings", None)
        if bool(getattr(settings, "agent_memory_curator_enabled", False)):
            auto_promote = bool(getattr(settings, "agent_memory_auto_promote_on_merge", True))
            curator = MemoryCurator(store=self.store)
            decision = curator.evaluate_branch_promotion(
                branch_record=branch_record,
                findings=promotable_findings,
                context=context,
                auto_promote=auto_promote,
            )
            if not auto_promote:
                self._last_memory_curator_decision = decision.model_dump(mode="json")
                return []
            records = [
                curator.candidate_to_write_request(
                    candidate=candidate,
                    branch_record=branch_record,
                    context=context,
                    tags=list(tags),
                )
                for candidate in decision.candidates
            ]
            keys = (memory_writer or MemoryWriter(store=self.store)).write_records(records)
            decision.promoted_memory_ids = keys
            self._last_memory_curator_decision = decision.model_dump(mode="json")
            return keys
        if memory_writer is not None:
            records = [
                MemoryWriteRequest(
                    kind=MemoryKind.BRANCH_FINDING,
                    scope=MemoryScope.ROOT_THREAD,
                    visibility=MemoryVisibility.SHARED,
                    namespace=namespace,
                    content=item.finding,
                    summary=item.finding,
                    tags=list(tags),
                    evidence_refs=item.evidence_refs,
                    source_thread_id=source_thread_id,
                    source_branch_id=branch_record.branch_id,
                    root_thread_id=context.root_thread_id,
                    user_id=context.user_id,
                    confidence=item.confidence,
                    promoted_to_main=True,
                )
                for item in promotable_findings
            ]
            return memory_writer.write_records(records)

        keys: list[str] = []
        for item in promotable_findings:
            key = str(uuid.uuid4())
            self.store.put(
                namespace,
                key,
                {
                    "type": "promoted_branch_finding",
                    "branch_id": branch_record.branch_id,
                    "branch_name": branch_record.branch_name,
                    "summary": item.finding,
                    "evidence_refs": item.evidence_refs,
                    "confidence": item.confidence,
                    "merge_importable": item.merge_importable,
                    "tags": list(tags),
                    "promoted_to_main": True,
                    "source_thread_id": source_thread_id,
                    "source_branch_id": branch_record.branch_id,
                    "root_thread_id": context.root_thread_id,
                    "user_id": context.user_id,
                },
            )
            keys.append(key)
        return keys

    @staticmethod
    def _coerce_finding_item(value: object) -> FindingItem:
        if isinstance(value, FindingItem):
            return value
        if isinstance(value, dict):
            return FindingItem.model_validate(value)
        return FindingItem(finding=str(value))

    @staticmethod
    def _build_branch_request_context(branch_record: BranchRecord) -> RequestContext:
        return RequestContext(
            user_id=branch_record.owner_user_id,
            root_thread_id=branch_record.root_thread_id,
            branch_id=branch_record.branch_id,
            parent_thread_id=branch_record.parent_thread_id,
            branch_role=branch_record.branch_role.value,
        )
