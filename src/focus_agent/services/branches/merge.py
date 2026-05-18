from __future__ import annotations

import logging
from copy import deepcopy

from langchain.messages import SystemMessage

from ...core.branching import (
    BranchStatus,
    ImportedConclusion,
    MergeDecision,
    MergeProposal,
    MergeProposalOverrides,
    MergeTarget,
)
from ...core.request_context import RequestContext
from ...core.types import FindingItem

logger = logging.getLogger("focus_agent.branches")


class BranchMergeCoordinator:
    """Owns merge proposal and merge decision workflows behind BranchService."""

    def __init__(self, service):
        self.service = service

    def prepare_merge_proposal(self, *, child_thread_id: str, user_id: str) -> MergeProposal:
        svc = self.service
        svc.repo.assert_thread_owner(thread_id=child_thread_id, owner_user_id=user_id)
        branch_record = svc.repo.get_by_child_thread_id(child_thread_id)
        svc._ensure_branch_not_merged(branch_record)
        child_config = {"configurable": {"thread_id": child_thread_id}}
        snapshot = svc.graph.get_state(child_config)
        values = deepcopy(snapshot.values)
        svc.repo.update_status(branch_record.branch_id, BranchStatus.PREPARING_MERGE_REVIEW)
        preparing_record = svc.repo.get(branch_record.branch_id)
        svc.graph.update_state(
            child_config,
            {
                "branch_meta": svc._branch_meta_payload_from_record(
                    preparing_record,
                    existing_meta=dict(values.get("branch_meta") or {}),
                ),
            },
            as_node="bootstrap_turn",
        )
        svc._persist_branch_findings_to_branch_memory(
            branch_record=branch_record,
            findings=list(values.get("branch_local_findings", [])),
        )
        try:
            from focus_agent.services import branches as branch_module

            proposal = branch_module.generate_merge_proposal(
                svc.proposal_model,
                values,
                values.get("branch_meta"),
            )
            svc.repo.save_merge_proposal(branch_record.branch_id, proposal)
            svc.repo.update_status(branch_record.branch_id, BranchStatus.AWAITING_MERGE_REVIEW)
            updated_record = svc.repo.get(branch_record.branch_id)

            svc.graph.update_state(
                child_config,
                {
                    "merge_proposal": proposal.model_dump(mode="json"),
                    "branch_meta": svc._branch_meta_payload_from_record(
                        updated_record,
                        existing_meta=dict(values.get("branch_meta") or {}),
                    ),
                },
                as_node="summarize_turn",
            )
            return proposal
        except Exception:  # noqa: BLE001 - revert transient status before surfacing proposal errors
            logger.warning(
                "failed to prepare merge proposal; reverting branch status",
                extra={"branch_id": branch_record.branch_id, "child_thread_id": child_thread_id},
                exc_info=True,
            )
            svc.repo.update_status(branch_record.branch_id, BranchStatus.ACTIVE)
            reverted_record = svc.repo.get(branch_record.branch_id)
            svc.graph.update_state(
                child_config,
                {
                    "branch_meta": svc._branch_meta_payload_from_record(
                        reverted_record,
                        existing_meta=dict(values.get("branch_meta") or {}),
                    ),
                },
                as_node="bootstrap_turn",
            )
            raise

    def apply_merge_decision(
        self,
        *,
        child_thread_id: str,
        decision: MergeDecision,
        context: RequestContext,
        proposal_overrides: MergeProposalOverrides | None = None,
    ) -> ImportedConclusion | None:
        svc = self.service
        svc.repo.assert_thread_owner(thread_id=child_thread_id, owner_user_id=context.user_id)
        branch_record = svc.repo.get_by_child_thread_id(child_thread_id)
        svc._ensure_branch_not_merged(branch_record)
        child_config = {"configurable": {"thread_id": child_thread_id}}
        snapshot = svc.graph.get_state(child_config)
        values = deepcopy(snapshot.values)
        proposal_dict = values.get("merge_proposal") or branch_record.merge_proposal
        if not proposal_dict:
            raise ValueError("No merge proposal found for this child thread.")
        proposal = svc._apply_merge_proposal_overrides(
            proposal=MergeProposal.model_validate(proposal_dict),
            overrides=proposal_overrides,
        )
        blocked_reason = _merge_import_blocked_reason(values)
        if decision.approved and decision.mode.value != "none" and blocked_reason:
            raise ValueError(f"Merge import blocked by answer verification gate: {blocked_reason}")
        if decision.approved and decision.mode.value == "none":
            raise ValueError("Approved merge decisions must import at least a summary.")
        if proposal_overrides is not None:
            svc.repo.save_merge_proposal(branch_record.branch_id, proposal)

        svc.repo.save_merge_decision(branch_record.branch_id, decision)
        svc.graph.update_state(
            child_config,
            {
                "merge_proposal": proposal.model_dump(mode="json"),
                "merge_decision": decision.model_dump(mode="json"),
            },
            as_node="maybe_interrupt_for_merge",
        )

        if not decision.approved:
            svc.repo.update_status(branch_record.branch_id, BranchStatus.DISCARDED)
            discarded_record = svc.repo.get(branch_record.branch_id)
            svc.graph.update_state(
                child_config,
                {
                    "branch_meta": svc._branch_meta_payload_from_record(
                        discarded_record,
                        existing_meta=dict(values.get("branch_meta") or {}),
                    )
                },
                as_node="bootstrap_turn",
            )
            return None

        artifacts = proposal.artifacts
        if decision.mode.value == "selected_artifacts" and decision.selected_artifacts:
            allowed = set(decision.selected_artifacts)
            artifacts = [a for a in proposal.artifacts if a in allowed]

        imported = ImportedConclusion(
            branch_id=branch_record.branch_id,
            branch_name=branch_record.branch_name,
            mode=decision.mode,
            summary=proposal.summary,
            key_findings=proposal.key_findings,
            evidence_refs=proposal.evidence_refs if decision.mode.value != "summary_only" else [],
            artifacts=artifacts,
            rationale=decision.rationale,
        )

        imported_findings = [
            FindingItem(
                finding=item,
                evidence_refs=proposal.evidence_refs
                if decision.mode.value != "summary_only"
                else [],
                source_branch_id=branch_record.branch_id,
            )
            for item in proposal.key_findings
        ]

        target_thread_id = (
            branch_record.root_thread_id
            if decision.target == MergeTarget.ROOT_THREAD
            else branch_record.return_thread_id
        )
        target_config = {"configurable": {"thread_id": target_thread_id}}
        target_snapshot = svc.graph.get_state(target_config)
        target_values = deepcopy(getattr(target_snapshot, "values", {}) or {})
        import_notice = SystemMessage(content=svc._imported_conclusion_message(imported))
        svc.graph.update_state(
            target_config,
            {
                "messages": [import_notice],
                "rolling_summary": svc._append_imported_summary(
                    target_values.get("rolling_summary"),
                    imported,
                ),
                "merge_queue": [imported.model_dump(mode="json")],
                "imported_findings": [
                    finding.model_dump(mode="json") for finding in imported_findings
                ],
            },
            as_node="bootstrap_turn",
        )
        is_returning_to_root_main = target_thread_id == branch_record.root_thread_id
        if svc.store is not None and is_returning_to_root_main:
            memory_context = RequestContext(
                user_id=context.user_id,
                root_thread_id=branch_record.root_thread_id,
                parent_thread_id=target_thread_id,
                branch_id=branch_record.branch_id,
                branch_role=branch_record.branch_role.value,
            )
            svc._write_imported_conclusion_to_main_memory(
                branch_record=branch_record,
                context=memory_context,
                imported=imported,
            )
            svc.promote_branch_findings_to_main_memory(
                branch_record=branch_record,
                findings=list(values.get("branch_local_findings", [])),
                memory_context=memory_context,
            )
            if svc._last_memory_curator_decision is not None:
                svc.graph.update_state(
                    target_config,
                    {
                        "memory_curator_decision": svc._last_memory_curator_decision,
                        "plan_meta": {
                            **dict(target_values.get("plan_meta") or {}),
                            "memory_curator_decision": svc._last_memory_curator_decision,
                        },
                    },
                    as_node="bootstrap_turn",
                )
        svc.repo.update_status(branch_record.branch_id, BranchStatus.MERGED)
        merged_record = svc.repo.get(branch_record.branch_id)
        svc.graph.update_state(
            child_config,
            {
                "branch_meta": svc._branch_meta_payload_from_record(
                    merged_record,
                    existing_meta=dict(values.get("branch_meta") or {}),
                )
            },
            as_node="bootstrap_turn",
        )
        return imported


def _merge_import_blocked_reason(values: dict) -> str:
    verification = values.get("answer_verification") or (values.get("plan_meta") or {}).get(
        "answer_verification"
    )
    if not isinstance(verification, dict):
        return ""
    status = str(verification.get("status") or "").strip()
    if status in {"unsupported", "contradicted", "blocked"}:
        return status
    return ""
import uuid

from ...core.branching import BranchRecord, ImportedConclusion
from ...core.request_context import RequestContext
from ...core.types import FindingItem
from ...memory import MemoryCurator, MemoryWriter
from ...memory.models import MemoryKind, MemoryScope, MemoryVisibility, MemoryWriteRequest
from ...storage.namespaces import branch_namespace, conversation_main_namespace


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
            curator = MemoryCurator(
                store=self.store,
                repository=getattr(memory_writer, "repository", None),
            )
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


__all__ = ["BranchMergeCoordinator", "BranchMemoryPromotionMixin"]
