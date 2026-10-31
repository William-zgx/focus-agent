from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from copy import deepcopy
from typing import Any

from ...core.branching import BranchRecord, BranchRole, BranchStatus, BranchTreeNode


class BranchTreeCoordinator:
    """Owns branch tree and archive operations behind BranchService."""

    def __init__(self, service):
        self.service = service

    def get_branch_tree(self, *, root_thread_id: str, user_id: str) -> BranchTreeNode:
        svc = self.service
        resolution = svc._resolve_thread_ref(thread_id=root_thread_id, user_id=user_id)
        root_thread_id = resolution.root_thread_id
        svc._ensure_root_thread_access(root_thread_id=root_thread_id, user_id=user_id)
        records = svc.repo.list_by_root_thread_id(root_thread_id)
        try:
            conversation = svc.repo.get_conversation(root_thread_id)
            root_branch_name = conversation.title
        except Exception:
            root_branch_name = "main"
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
            children=[
                svc._build_tree_node(child, by_parent)
                for child in by_parent.get(root_thread_id, [])
            ],
        )

    def list_archived_branches(self, *, root_thread_id: str, user_id: str) -> list[BranchTreeNode]:
        svc = self.service
        resolution = svc._resolve_thread_ref(thread_id=root_thread_id, user_id=user_id)
        root_thread_id = resolution.root_thread_id
        svc._ensure_root_thread_access(root_thread_id=root_thread_id, user_id=user_id)
        records = svc.repo.list_by_root_thread_id(root_thread_id)
        archived_records = [record for record in records if record.is_archived]
        archived_records.sort(
            key=lambda record: (record.branch_depth, record.branch_name, record.child_thread_id)
        )
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

    def set_branch_archive_state(
        self, *, child_thread_id: str, user_id: str, is_archived: bool
    ) -> BranchRecord:
        svc = self.service
        branch_record = svc._require_child_branch_record(
            child_thread_id=child_thread_id,
            user_id=user_id,
            operation="Archiving or activating a branch",
        )
        svc.repo.update_archive_state(branch_record.branch_id, is_archived=is_archived)
        updated_record = svc.repo.get(branch_record.branch_id)

        if svc.graph is not None:
            child_config = {"configurable": {"thread_id": child_thread_id}}
            snapshot = svc.graph.get_state(child_config)
            values = deepcopy(snapshot.values)
            branch_meta = svc._branch_meta_payload_from_record(
                updated_record,
                existing_meta=dict(values.get("branch_meta") or {}),
            )
            svc.graph.update_state(
                child_config,
                {"branch_meta": branch_meta},
                as_node="bootstrap_turn",
            )
        return updated_record


def _checkpoint_timestamp(graph: Any, thread_id: str) -> str | None:
    config = {"configurable": {"thread_id": thread_id}}
    checkpointer = getattr(graph, "checkpointer", None)
    get_tuple = getattr(checkpointer, "get_tuple", None)
    if callable(get_tuple):
        try:
            checkpoint_tuple = get_tuple(config)
        except Exception:  # noqa: BLE001 - activity is best-effort display metadata
            checkpoint_tuple = None
        checkpoint = getattr(checkpoint_tuple, "checkpoint", None)
        if isinstance(checkpoint, dict) and checkpoint.get("ts"):
            return str(checkpoint["ts"])
    get_state = getattr(graph, "get_state", None)
    if not callable(get_state):
        return None
    try:
        snapshot = get_state(config)
    except Exception:  # noqa: BLE001 - activity is best-effort display metadata
        return None
    created_at = getattr(snapshot, "created_at", None)
    return str(created_at) if created_at else None


def thread_last_activity_at(graph: Any, thread_ids: Iterable[str]) -> dict[str, str]:
    """Return the latest checkpoint timestamp per thread.

    Branch records carry no activity timestamps, so the newest LangGraph
    checkpoint ``ts`` of each thread (written on every turn and state update)
    is the best available "last activity" signal. Threads without a readable
    checkpoint are omitted.
    """
    if graph is None:
        return {}
    activity: dict[str, str] = {}
    for thread_id in dict.fromkeys(str(item) for item in thread_ids if item):
        timestamp = _checkpoint_timestamp(graph, thread_id)
        if timestamp:
            activity[thread_id] = timestamp
    return activity


__all__ = ["BranchTreeCoordinator", "thread_last_activity_at"]
