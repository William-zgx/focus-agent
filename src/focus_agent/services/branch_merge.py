from __future__ import annotations

from copy import deepcopy

from langchain.messages import SystemMessage

from ..core.branching import (
    BranchStatus,
    ImportedConclusion,
    MergeDecision,
    MergeProposal,
    MergeProposalOverrides,
    MergeTarget,
)
from ..core.request_context import RequestContext
from ..core.types import FindingItem


class BranchMergeCoordinator:
    """Owns merge proposal and merge decision workflows behind BranchService."""

    def __init__(self, service):
        self.service = service

    def prepare_merge_proposal(self, *, child_thread_id: str, user_id: str) -> MergeProposal:
        svc = self.service
        svc.repo.assert_thread_owner(thread_id=child_thread_id, owner_user_id=user_id)
        branch_record = svc.repo.get_by_child_thread_id(child_thread_id)
        svc._ensure_branch_not_merged(branch_record)
        child_config = {'configurable': {'thread_id': child_thread_id}}
        snapshot = svc.graph.get_state(child_config)
        values = deepcopy(snapshot.values)
        svc.repo.update_status(branch_record.branch_id, BranchStatus.PREPARING_MERGE_REVIEW)
        preparing_record = svc.repo.get(branch_record.branch_id)
        svc.graph.update_state(
            child_config,
            {
                'branch_meta': svc._branch_meta_payload_from_record(
                    preparing_record,
                    existing_meta=dict(values.get('branch_meta') or {}),
                ),
            },
            as_node='bootstrap_turn',
        )
        svc._persist_branch_findings_to_branch_memory(
            branch_record=branch_record,
            findings=list(values.get('branch_local_findings', [])),
        )
        try:
            from focus_agent.services import branches as branch_module

            proposal = branch_module.generate_merge_proposal(
                svc.proposal_model,
                values,
                values.get('branch_meta'),
            )
            svc.repo.save_merge_proposal(branch_record.branch_id, proposal)
            svc.repo.update_status(branch_record.branch_id, BranchStatus.AWAITING_MERGE_REVIEW)
            updated_record = svc.repo.get(branch_record.branch_id)

            svc.graph.update_state(
                child_config,
                {
                    'merge_proposal': proposal.model_dump(mode='json'),
                    'branch_meta': svc._branch_meta_payload_from_record(
                        updated_record,
                        existing_meta=dict(values.get('branch_meta') or {}),
                    ),
                },
                as_node='summarize_turn',
            )
            return proposal
        except Exception:
            svc.repo.update_status(branch_record.branch_id, BranchStatus.ACTIVE)
            reverted_record = svc.repo.get(branch_record.branch_id)
            svc.graph.update_state(
                child_config,
                {
                    'branch_meta': svc._branch_meta_payload_from_record(
                        reverted_record,
                        existing_meta=dict(values.get('branch_meta') or {}),
                    ),
                },
                as_node='bootstrap_turn',
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
        child_config = {'configurable': {'thread_id': child_thread_id}}
        snapshot = svc.graph.get_state(child_config)
        values = deepcopy(snapshot.values)
        proposal_dict = values.get('merge_proposal') or branch_record.merge_proposal
        if not proposal_dict:
            raise ValueError('No merge proposal found for this child thread.')
        proposal = svc._apply_merge_proposal_overrides(
            proposal=MergeProposal.model_validate(proposal_dict),
            overrides=proposal_overrides,
        )
        if proposal_overrides is not None:
            svc.repo.save_merge_proposal(branch_record.branch_id, proposal)

        svc.repo.save_merge_decision(branch_record.branch_id, decision)
        svc.graph.update_state(
            child_config,
            {
                'merge_proposal': proposal.model_dump(mode='json'),
                'merge_decision': decision.model_dump(mode='json'),
            },
            as_node='maybe_interrupt_for_merge',
        )

        if not decision.approved or decision.mode.value == 'none':
            svc.repo.update_status(branch_record.branch_id, BranchStatus.DISCARDED)
            discarded_record = svc.repo.get(branch_record.branch_id)
            svc.graph.update_state(
                child_config,
                {
                    'branch_meta': svc._branch_meta_payload_from_record(
                        discarded_record,
                        existing_meta=dict(values.get('branch_meta') or {}),
                    )
                },
                as_node='bootstrap_turn',
            )
            return None

        artifacts = proposal.artifacts
        if decision.mode.value == 'selected_artifacts' and decision.selected_artifacts:
            allowed = set(decision.selected_artifacts)
            artifacts = [a for a in proposal.artifacts if a in allowed]

        imported = ImportedConclusion(
            branch_id=branch_record.branch_id,
            branch_name=branch_record.branch_name,
            mode=decision.mode,
            summary=proposal.summary,
            key_findings=proposal.key_findings,
            evidence_refs=proposal.evidence_refs if decision.mode.value != 'summary_only' else [],
            artifacts=artifacts,
            rationale=decision.rationale,
        )

        imported_findings = [
            FindingItem(
                finding=item,
                evidence_refs=proposal.evidence_refs if decision.mode.value != 'summary_only' else [],
                source_branch_id=branch_record.branch_id,
            )
            for item in proposal.key_findings
        ]

        target_thread_id = (
            branch_record.root_thread_id
            if decision.target == MergeTarget.ROOT_THREAD
            else branch_record.return_thread_id
        )
        target_config = {'configurable': {'thread_id': target_thread_id}}
        target_snapshot = svc.graph.get_state(target_config)
        target_values = deepcopy(getattr(target_snapshot, "values", {}) or {})
        import_notice = SystemMessage(content=svc._imported_conclusion_message(imported))
        svc.graph.update_state(
            target_config,
            {
                'messages': [import_notice],
                'rolling_summary': svc._append_imported_summary(
                    target_values.get('rolling_summary'),
                    imported,
                ),
                'merge_queue': [imported.model_dump(mode='json')],
                'imported_findings': [finding.model_dump(mode='json') for finding in imported_findings],
            },
            as_node='bootstrap_turn',
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
                findings=list(values.get('branch_local_findings', [])),
                memory_context=memory_context,
            )
            if svc._last_memory_curator_decision is not None:
                svc.graph.update_state(
                    target_config,
                    {
                        'memory_curator_decision': svc._last_memory_curator_decision,
                        'plan_meta': {
                            **dict(target_values.get('plan_meta') or {}),
                            'memory_curator_decision': svc._last_memory_curator_decision,
                        },
                    },
                    as_node='bootstrap_turn',
                )
        svc.repo.update_status(branch_record.branch_id, BranchStatus.MERGED)
        merged_record = svc.repo.get(branch_record.branch_id)
        svc.graph.update_state(
            child_config,
            {
                'branch_meta': svc._branch_meta_payload_from_record(
                    merged_record,
                    existing_meta=dict(values.get('branch_meta') or {}),
                )
            },
            as_node='bootstrap_turn',
        )
        return imported
