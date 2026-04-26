from __future__ import annotations

from collections import defaultdict
from copy import deepcopy

from ..core.branching import BranchRecord, BranchRole, BranchStatus, BranchTreeNode


class BranchTreeCoordinator:
    """Owns branch tree and archive operations behind BranchService."""

    def __init__(self, service):
        self.service = service

    def get_branch_tree(self, *, root_thread_id: str, user_id: str) -> BranchTreeNode:
        svc = self.service
        svc._ensure_root_thread_access(root_thread_id=root_thread_id, user_id=user_id)
        records = svc.repo.list_by_root_thread_id(root_thread_id)
        try:
            conversation = svc.repo.get_conversation(root_thread_id)
            root_branch_name = conversation.title
        except Exception:
            root_branch_name = 'main'
        by_parent: dict[str, list[BranchRecord]] = defaultdict(list)
        for record in records:
            if record.is_archived:
                continue
            by_parent[record.parent_thread_id].append(record)

        return BranchTreeNode(
            thread_id=root_thread_id,
            root_thread_id=root_thread_id,
            branch_name=root_branch_name,
            branch_role=BranchRole.MAIN,
            branch_status=BranchStatus.ACTIVE,
            is_archived=False,
            branch_depth=0,
            children=[svc._build_tree_node(child, by_parent) for child in by_parent.get(root_thread_id, [])],
        )

    def list_archived_branches(self, *, root_thread_id: str, user_id: str) -> list[BranchTreeNode]:
        svc = self.service
        svc._ensure_root_thread_access(root_thread_id=root_thread_id, user_id=user_id)
        records = svc.repo.list_by_root_thread_id(root_thread_id)
        archived_records = [record for record in records if record.is_archived]
        archived_records.sort(key=lambda record: (record.branch_depth, record.branch_name, record.child_thread_id))
        return [
            BranchTreeNode(
                thread_id=record.child_thread_id,
                root_thread_id=record.root_thread_id,
                parent_thread_id=record.parent_thread_id,
                branch_id=record.branch_id,
                branch_name=record.branch_name,
                branch_role=record.branch_role,
                branch_status=record.branch_status,
                is_archived=True,
                archived_at=record.archived_at,
                branch_depth=record.branch_depth,
                fork_strategy=record.fork_strategy,
            )
            for record in archived_records
        ]

    def set_branch_archive_state(self, *, child_thread_id: str, user_id: str, is_archived: bool) -> BranchRecord:
        svc = self.service
        svc.repo.assert_thread_owner(thread_id=child_thread_id, owner_user_id=user_id)
        branch_record = svc.repo.get_by_child_thread_id(child_thread_id)
        svc.repo.update_archive_state(branch_record.branch_id, is_archived=is_archived)
        updated_record = svc.repo.get(branch_record.branch_id)

        if svc.graph is not None:
            child_config = {'configurable': {'thread_id': child_thread_id}}
            snapshot = svc.graph.get_state(child_config)
            values = deepcopy(snapshot.values)
            branch_meta = svc._branch_meta_payload_from_record(
                updated_record,
                existing_meta=dict(values.get('branch_meta') or {}),
            )
            svc.graph.update_state(
                child_config,
                {'branch_meta': branch_meta},
                as_node='bootstrap_turn',
            )
        return updated_record
