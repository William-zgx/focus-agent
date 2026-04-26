from __future__ import annotations

from copy import deepcopy
import uuid

from ..core.branching import BranchMeta, BranchRecord, BranchRole, BranchStatus
from ..core.types import ConversationRecord


class BranchLifecycleCoordinator:
    """Owns branch lifecycle operations behind the BranchService facade."""

    def __init__(self, service):
        self.service = service

    def fork_branch(
        self,
        *,
        parent_thread_id: str,
        user_id: str,
        branch_name: str | None = None,
        name_source: str | None = None,
        language: str | None = None,
        branch_role: BranchRole = BranchRole.EXPLORE_ALTERNATIVES,
        fork_checkpoint_id: str | None = None,
    ) -> BranchRecord:
        svc = self.service
        svc._ensure_parent_thread_access(parent_thread_id=parent_thread_id, user_id=user_id)
        parent_config = {'configurable': {'thread_id': parent_thread_id}}
        parent_snapshot = svc.graph.get_state(parent_config)
        parent_values = deepcopy(parent_snapshot.values)
        svc._ensure_parent_branch_can_fork(
            parent_thread_id=parent_thread_id,
            parent_values=parent_values,
        )
        root_thread_id = svc._derive_root_thread_id(parent_thread_id, parent_values)
        next_branch_depth = svc._ensure_branch_depth_allowed(
            parent_thread_id=parent_thread_id,
            parent_values=parent_values,
        )
        resolved_branch_name = svc._resolve_initial_branch_name(
            preferred_name=branch_name,
            parent_values=parent_values,
            name_source=name_source,
            branch_role=branch_role,
            language=language,
        )
        branch_id = str(uuid.uuid4())

        if svc.thread_client and fork_checkpoint_id is None:
            copied = svc.thread_client.threads.copy(parent_thread_id)
            child_thread_id = copied['thread_id']
            fork_strategy = 'copy_thread'
        else:
            child_thread_id = str(uuid.uuid4())
            fork_strategy = 'local_snapshot_seed'
            svc.graph.update_state(
                {'configurable': {'thread_id': child_thread_id}},
                parent_values,
                as_node='bootstrap_turn',
            )

        branch_meta = BranchMeta(
            branch_id=branch_id,
            root_thread_id=root_thread_id,
            parent_thread_id=parent_thread_id,
            return_thread_id=parent_thread_id,
            branch_name=resolved_branch_name,
            branch_role=branch_role,
            branch_depth=next_branch_depth,
            branch_status=BranchStatus.ACTIVE,
            fork_checkpoint_id=fork_checkpoint_id,
            fork_strategy=fork_strategy,
        )
        branch_meta_payload = branch_meta.model_dump(mode='json')
        branch_meta_payload['branch_name_pending_ai'] = branch_name is None
        branch_meta_payload['branch_role_pending_ai'] = branch_role == BranchRole.EXPLORE_ALTERNATIVES

        svc.graph.update_state(
            {'configurable': {'thread_id': child_thread_id}},
            {
                'branch_meta': branch_meta_payload,
                'merge_proposal': None,
                'merge_decision': None,
                'branch_local_findings': [],
            },
            as_node='bootstrap_turn',
        )
        svc.repo.ensure_thread_owner(
            thread_id=child_thread_id,
            root_thread_id=root_thread_id,
            owner_user_id=user_id,
        )

        record = BranchRecord(
            branch_id=branch_id,
            root_thread_id=root_thread_id,
            parent_thread_id=parent_thread_id,
            child_thread_id=child_thread_id,
            return_thread_id=parent_thread_id,
            owner_user_id=user_id,
            branch_name=resolved_branch_name,
            branch_role=branch_role,
            branch_depth=branch_meta.branch_depth,
            branch_status=BranchStatus.ACTIVE,
            fork_checkpoint_id=fork_checkpoint_id,
            fork_strategy=fork_strategy,
        )
        svc.repo.create(record)
        return record

    def refresh_branch_role(
        self,
        *,
        child_thread_id: str,
        user_id: str,
        force: bool = False,
    ) -> BranchRecord | None:
        svc = self.service
        svc.repo.assert_thread_owner(thread_id=child_thread_id, owner_user_id=user_id)
        branch_record = svc.repo.get_by_child_thread_id(child_thread_id)
        child_config = {'configurable': {'thread_id': child_thread_id}}
        child_snapshot = svc.graph.get_state(child_config)
        child_values = deepcopy(child_snapshot.values)
        existing_meta = dict(child_values.get('branch_meta') or {})
        if not force and not existing_meta.get('branch_role_pending_ai'):
            return branch_record

        next_role = svc._classify_branch_role(
            thread_values=child_values,
            current_role=branch_record.branch_role,
        )
        if next_role == branch_record.branch_role:
            return branch_record

        svc.repo.update_branch_role(branch_record.branch_id, next_role)
        updated_record = branch_record.model_copy(update={'branch_role': next_role})
        svc.graph.update_state(
            child_config,
            {'branch_meta': svc._branch_meta_payload_from_record(updated_record, existing_meta)},
            as_node='bootstrap_turn',
        )
        return updated_record

    def refresh_branch_name(
        self,
        *,
        child_thread_id: str,
        user_id: str,
        name_source: str | None = None,
        force: bool = False,
    ) -> BranchRecord | None:
        svc = self.service
        svc.repo.assert_thread_owner(thread_id=child_thread_id, owner_user_id=user_id)
        branch_record = svc.repo.get_by_child_thread_id(child_thread_id)
        if not force and not branch_record.branch_name.strip():
            force = True
        if svc.proposal_model is None and not force:
            return branch_record

        child_config = {'configurable': {'thread_id': child_thread_id}}
        child_snapshot = svc.graph.get_state(child_config)
        child_values = deepcopy(child_snapshot.values)
        generated_name = svc._generate_branch_name(
            thread_values=child_values,
            branch_role=branch_record.branch_role,
        )
        next_name = svc._sanitize_branch_name(generated_name, branch_role=branch_record.branch_role)
        if not next_name or next_name == branch_record.branch_name:
            return branch_record

        svc.repo.update_branch_name(branch_record.branch_id, next_name)
        existing_meta = child_values.get('branch_meta') or {}
        updated_record = branch_record.model_copy(update={'branch_name': next_name})
        svc.graph.update_state(
            child_config,
            {'branch_meta': svc._branch_meta_payload_from_record(updated_record, existing_meta)},
            as_node='bootstrap_turn',
        )
        return updated_record

    def refresh_branch_metadata_after_first_turn(
        self,
        *,
        child_thread_id: str,
        user_id: str,
    ) -> BranchRecord | None:
        svc = self.service
        try:
            svc.repo.assert_thread_owner(thread_id=child_thread_id, owner_user_id=user_id)
            child_config = {'configurable': {'thread_id': child_thread_id}}
            child_snapshot = svc.graph.get_state(child_config)
            child_values = deepcopy(child_snapshot.values)
            existing_meta = dict(child_values.get('branch_meta') or {})
            pending_name = bool(existing_meta.get('branch_name_pending_ai'))
            pending_role = bool(existing_meta.get('branch_role_pending_ai'))
            if not pending_name and not pending_role:
                return None

            updated_record = svc.repo.get_by_child_thread_id(child_thread_id)
            if pending_role:
                refreshed_role_record = self.refresh_branch_role(
                    child_thread_id=child_thread_id,
                    user_id=user_id,
                    force=True,
                )
                if refreshed_role_record is not None:
                    updated_record = refreshed_role_record
            if pending_name:
                refreshed_name_record = self.refresh_branch_name(
                    child_thread_id=child_thread_id,
                    user_id=user_id,
                    name_source=None,
                    force=True,
                )
                if refreshed_name_record is not None:
                    updated_record = refreshed_name_record

            refreshed_snapshot = svc.graph.get_state(child_config)
            refreshed_values = deepcopy(refreshed_snapshot.values)
            refreshed_meta = dict(refreshed_values.get('branch_meta') or {})
            refreshed_meta['branch_name_pending_ai'] = False
            refreshed_meta['branch_role_pending_ai'] = False
            svc.graph.update_state(
                child_config,
                {'branch_meta': refreshed_meta},
                as_node='bootstrap_turn',
            )
            return updated_record
        except Exception:
            return None

    def rename_branch(
        self,
        *,
        child_thread_id: str,
        user_id: str,
        branch_name: str,
    ) -> BranchRecord:
        svc = self.service
        svc.repo.assert_thread_owner(thread_id=child_thread_id, owner_user_id=user_id)
        branch_record = svc.repo.get_by_child_thread_id(child_thread_id)
        next_name = svc._sanitize_branch_name(branch_name, branch_role=branch_record.branch_role)
        svc.repo.update_branch_name(branch_record.branch_id, next_name)
        child_config = {'configurable': {'thread_id': child_thread_id}}
        snapshot = svc.graph.get_state(child_config)
        values = deepcopy(snapshot.values)
        updated_record = branch_record.model_copy(update={'branch_name': next_name})
        updated_meta = svc._branch_meta_payload_from_record(
            updated_record,
            existing_meta=dict(values.get('branch_meta') or {}),
        )
        updated_meta['branch_name_pending_ai'] = False
        svc.graph.update_state(
            child_config,
            {'branch_meta': updated_meta},
            as_node='bootstrap_turn',
        )
        return updated_record

    def refresh_conversation_title_after_first_turn(
        self,
        *,
        root_thread_id: str,
        user_id: str,
    ) -> ConversationRecord | None:
        svc = self.service
        try:
            svc.repo.assert_thread_owner(thread_id=root_thread_id, owner_user_id=user_id)
            record = svc.repo.get_conversation(root_thread_id)
            if not record.title_pending_ai:
                return None
            snapshot = svc.graph.get_state({'configurable': {'thread_id': root_thread_id}})
            values = deepcopy(getattr(snapshot, 'values', {}) or {})
            generated_name = svc._generate_conversation_name(thread_values=values)
            next_title = svc._sanitize_branch_name(generated_name, branch_role=BranchRole.MAIN)
            return svc.repo.update_conversation_title(
                root_thread_id=root_thread_id,
                owner_user_id=user_id,
                title=next_title,
                title_pending_ai=False,
            )
        except Exception:
            return None

    def set_conversation_archive_state(
        self,
        *,
        root_thread_id: str,
        user_id: str,
        is_archived: bool,
    ) -> ConversationRecord:
        svc = self.service
        svc.repo.assert_thread_owner(thread_id=root_thread_id, owner_user_id=user_id)
        return svc.repo.update_conversation_archive_state(
            root_thread_id=root_thread_id,
            owner_user_id=user_id,
            is_archived=is_archived,
        )
