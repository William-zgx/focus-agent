from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager

from langgraph_sdk import get_sync_client

from .actions import BranchNamingPolicyMixin
from .merge import BranchMergeCoordinator, BranchMemoryPromotionMixin

from ...config import Settings
from ...core.branching import (
    BranchRecord,
    BranchRole,
    BranchStatus,
    BranchTreeNode,
    ImportedConclusion,
    MergeDecision,
    MergeProposal,
    MergeProposalOverrides,
    MergeTarget,
)
from ...core.merge_review import (
    generate_merge_proposal,  # noqa: F401 - compatibility monkeypatch hook
)
from ...core.request_context import RequestContext
from ...core.types import ConversationRecord
from ...memory import MemoryWriter
from ...model_registry import create_chat_model
from ...repositories.branch_repository import BranchRepository
from ..coordination import CoordinationBackend, create_in_memory_coordination_backend
from ..thread_turn_lease import ThreadTurnLeaseManager

logger = logging.getLogger("focus_agent.branches")


class BranchService(BranchMemoryPromotionMixin, BranchNamingPolicyMixin):
    _DEFAULT_MAX_BRANCH_DEPTH = 5

    def __init__(
        self,
        *,
        settings: Settings,
        graph,
        repo: BranchRepository,
        store=None,
        memory_writer: MemoryWriter | None = None,
    ):
        self.settings = settings
        self.graph = graph
        self.repo = repo
        self.store = store
        self.memory_writer = memory_writer
        self._coordination_backend: CoordinationBackend | None = None
        self._last_memory_curator_decision: dict[str, object] | None = None
        self.thread_client = get_sync_client(url=settings.langgraph_api_url) if settings.langgraph_api_url else None
        self.proposal_model = create_chat_model(
            settings.helper_model or settings.model,
            temperature=0,
            settings=settings,
        )
        self.lifecycle = BranchLifecycleCoordinator(self)
        self.merge_workflow = BranchMergeCoordinator(self)
        self.tree_view = BranchTreeCoordinator(self)

    def _lifecycle_coordinator(self) -> BranchLifecycleCoordinator:
        coordinator = getattr(self, "lifecycle", None)
        if coordinator is None:
            coordinator = BranchLifecycleCoordinator(self)
            self.lifecycle = coordinator
        return coordinator

    def _merge_coordinator(self) -> BranchMergeCoordinator:
        coordinator = getattr(self, "merge_workflow", None)
        if coordinator is None:
            coordinator = BranchMergeCoordinator(self)
            self.merge_workflow = coordinator
        return coordinator

    def _tree_coordinator(self) -> BranchTreeCoordinator:
        coordinator = getattr(self, "tree_view", None)
        if coordinator is None:
            coordinator = BranchTreeCoordinator(self)
            self.tree_view = coordinator
        return coordinator

    def _branch_coordination_backend(self) -> CoordinationBackend:
        backend = getattr(self, "_coordination_backend", None)
        if backend is None:
            backend = create_in_memory_coordination_backend()
            self._coordination_backend = backend
        return backend

    def _thread_turn_lock_ttl_seconds(self) -> float:
        settings = getattr(self, "settings", None)
        return max(float(getattr(settings, "runtime_thread_lock_ttl_seconds", 300.0) or 300.0), 1.0)

    def _thread_turn_lock_heartbeat_seconds(self) -> float:
        ttl_seconds = self._thread_turn_lock_ttl_seconds()
        settings = getattr(self, "settings", None)
        configured_seconds = float(getattr(settings, "runtime_thread_lock_heartbeat_seconds", 30.0) or 30.0)
        return max(min(ttl_seconds / 3.0, configured_seconds), 0.001)

    def _thread_turn_lease(self, *, thread_id: str) -> ThreadTurnLeaseManager:
        return ThreadTurnLeaseManager(
            backend=self._branch_coordination_backend().thread_turns,
            thread_id=thread_id,
            ttl_seconds=self._thread_turn_lock_ttl_seconds(),
            heartbeat_interval_seconds=self._thread_turn_lock_heartbeat_seconds(),
        )

    @contextmanager
    def _thread_write_lease(self, *, thread_id: str) -> Iterator[None]:
        with self._thread_turn_lease(thread_id=thread_id):
            yield

    @contextmanager
    def _thread_write_leases(self, *, thread_ids: list[str] | tuple[str, ...] | set[str]) -> Iterator[None]:
        ordered_thread_ids = sorted({str(thread_id) for thread_id in thread_ids if str(thread_id).strip()})
        with ExitStack() as stack:
            for thread_id in ordered_thread_ids:
                stack.enter_context(self._thread_turn_lease(thread_id=thread_id))
            yield

    @staticmethod
    def _clean_list_override(items: object) -> list[str]:
        cleaned: list[str] = []
        for item in items or []:
            text = str(item).strip()
            if text:
                cleaned.append(text)
        return cleaned

    def _apply_merge_proposal_overrides(
        self,
        *,
        proposal: MergeProposal,
        overrides: MergeProposalOverrides | None,
    ) -> MergeProposal:
        if overrides is None:
            return proposal

        proposal_payload = proposal.model_dump(mode='json')
        override_payload = overrides.model_dump(exclude_none=True, mode='json')
        if 'summary' in override_payload:
            override_payload['summary'] = str(override_payload['summary']).strip()
        for key in ('key_findings', 'open_questions', 'evidence_refs', 'artifacts'):
            if key in override_payload:
                override_payload[key] = self._clean_list_override(override_payload[key])

        merged = MergeProposal.model_validate({**proposal_payload, **override_payload})
        if not merged.summary.strip():
            raise ValueError('Merge proposal summary cannot be empty.')
        return merged

    def _derive_root_thread_id(self, parent_thread_id: str, parent_state: dict) -> str:
        meta = parent_state.get('branch_meta') or {}
        root_thread_id = meta.get('root_thread_id')
        if root_thread_id:
            return str(root_thread_id)
        try:
            record = self.repo.get_by_child_thread_id(parent_thread_id)
        except KeyError:
            return parent_thread_id
        return record.root_thread_id

    def _derive_parent_branch_depth(self, parent_thread_id: str, parent_state: dict) -> int:
        meta = parent_state.get('branch_meta') or {}
        if meta.get('branch_depth') is not None:
            return int(meta.get('branch_depth') or 0)
        try:
            record = self.repo.get_by_child_thread_id(parent_thread_id)
        except KeyError:
            return 0
        return record.branch_depth

    def _derive_parent_branch_status(self, parent_thread_id: str, parent_state: dict) -> BranchStatus | None:
        try:
            record = self.repo.get_by_child_thread_id(parent_thread_id)
        except KeyError:
            record = None
        if record is not None:
            return record.branch_status
        meta = parent_state.get('branch_meta') or {}
        raw_status = meta.get('branch_status')
        if raw_status is not None:
            try:
                return BranchStatus(str(raw_status))
            except ValueError:
                logger.warning(
                    "invalid branch_status in parent state",
                    extra={"parent_thread_id": parent_thread_id, "branch_status": raw_status},
                )
        return None

    def _max_branch_depth(self) -> int:
        settings = getattr(self, "settings", None)
        value = getattr(settings, "branch_max_depth", self._DEFAULT_MAX_BRANCH_DEPTH)
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return self._DEFAULT_MAX_BRANCH_DEPTH

    def _ensure_branch_depth_allowed(self, *, parent_thread_id: str, parent_values: dict) -> int:
        parent_depth = self._derive_parent_branch_depth(parent_thread_id, parent_values)
        next_depth = parent_depth + 1
        max_depth = self._max_branch_depth()
        if next_depth > max_depth:
            raise ValueError(f"Maximum branch depth is {max_depth}.")
        return next_depth

    def _ensure_parent_branch_can_fork(self, *, parent_thread_id: str, parent_values: dict) -> None:
        parent_status = self._derive_parent_branch_status(parent_thread_id, parent_values)
        if parent_status == BranchStatus.MERGED:
            raise ValueError("Merged branches cannot create new branches.")

    @staticmethod
    def _ensure_branch_not_merged(branch_record: BranchRecord) -> None:
        if branch_record.branch_status == BranchStatus.MERGED:
            raise ValueError("Merged branches are read-only.")

    @staticmethod
    def _branch_meta_payload_from_record(record: BranchRecord, existing_meta: dict | None = None) -> dict[str, object]:
        payload = dict(existing_meta or {})
        payload.pop('conclusion_policy', None)
        payload.update(
            {
                'branch_id': record.branch_id,
                'root_thread_id': record.root_thread_id,
                'parent_thread_id': record.parent_thread_id,
                'return_thread_id': record.return_thread_id,
                'branch_name': record.branch_name,
                'branch_role': record.branch_role.value,
                'branch_depth': record.branch_depth,
                'branch_status': record.branch_status.value,
                'is_archived': record.is_archived,
                'archived_at': record.archived_at,
                'fork_checkpoint_id': record.fork_checkpoint_id,
                'fork_strategy': record.fork_strategy,
            }
        )
        return payload

    def _build_tree_node(self, record: BranchRecord, by_parent: dict[str, list[BranchRecord]]) -> BranchTreeNode:
        return BranchTreeNode(
            thread_id=record.child_thread_id,
            root_thread_id=record.root_thread_id,
            parent_thread_id=record.parent_thread_id,
            branch_id=record.branch_id,
            branch_name=record.branch_name,
            branch_role=record.branch_role,
            branch_status=record.branch_status,
            is_archived=record.is_archived,
            archived_at=record.archived_at,
            branch_depth=record.branch_depth,
            fork_strategy=record.fork_strategy,
            children=[self._build_tree_node(child, by_parent) for child in by_parent.get(record.child_thread_id, [])],
        )

    def _ensure_root_thread_access(self, *, root_thread_id: str, user_id: str) -> None:
        owner = self.repo.get_thread_owner(thread_id=root_thread_id)
        if owner is None:
            self.repo.ensure_thread_owner(
                thread_id=root_thread_id,
                root_thread_id=root_thread_id,
                owner_user_id=user_id,
            )
            return
        self.repo.assert_thread_owner(thread_id=root_thread_id, owner_user_id=user_id)

    def _ensure_parent_thread_access(self, *, parent_thread_id: str, user_id: str) -> None:
        try:
            self.repo.get_by_child_thread_id(parent_thread_id)
        except KeyError:
            self._ensure_root_thread_access(root_thread_id=parent_thread_id, user_id=user_id)
            return
        self.repo.assert_thread_owner(thread_id=parent_thread_id, owner_user_id=user_id)

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
        return self._lifecycle_coordinator().fork_branch(
            parent_thread_id=parent_thread_id,
            user_id=user_id,
            branch_name=branch_name,
            name_source=name_source,
            language=language,
            branch_role=branch_role,
            fork_checkpoint_id=fork_checkpoint_id,
        )

    def refresh_branch_role(
        self,
        *,
        child_thread_id: str,
        user_id: str,
        force: bool = False,
    ) -> BranchRecord | None:
        with self._thread_write_lease(thread_id=child_thread_id):
            return self._lifecycle_coordinator().refresh_branch_role(
                child_thread_id=child_thread_id,
                user_id=user_id,
                force=force,
            )

    def refresh_branch_name(
        self,
        *,
        child_thread_id: str,
        user_id: str,
        name_source: str | None = None,
        force: bool = False,
    ) -> BranchRecord | None:
        with self._thread_write_lease(thread_id=child_thread_id):
            return self._lifecycle_coordinator().refresh_branch_name(
                child_thread_id=child_thread_id,
                user_id=user_id,
                name_source=name_source,
                force=force,
            )

    def refresh_branch_name_after_first_turn(
        self,
        *,
        child_thread_id: str,
        user_id: str,
    ) -> BranchRecord | None:
        return self.refresh_branch_metadata_after_first_turn(
            child_thread_id=child_thread_id,
            user_id=user_id,
        )

    def refresh_branch_metadata_after_first_turn(
        self,
        *,
        child_thread_id: str,
        user_id: str,
    ) -> BranchRecord | None:
        with self._thread_write_lease(thread_id=child_thread_id):
            return self._lifecycle_coordinator().refresh_branch_metadata_after_first_turn(
                child_thread_id=child_thread_id,
                user_id=user_id,
            )

    def rename_branch(
        self,
        *,
        child_thread_id: str,
        user_id: str,
        branch_name: str,
    ) -> BranchRecord:
        with self._thread_write_lease(thread_id=child_thread_id):
            return self._lifecycle_coordinator().rename_branch(
                child_thread_id=child_thread_id,
                user_id=user_id,
                branch_name=branch_name,
            )

    def refresh_conversation_title_after_first_turn(
        self,
        *,
        root_thread_id: str,
        user_id: str,
    ) -> ConversationRecord | None:
        return self._lifecycle_coordinator().refresh_conversation_title_after_first_turn(
            root_thread_id=root_thread_id,
            user_id=user_id,
        )

    def _set_conversation_archive_state(
        self,
        *,
        root_thread_id: str,
        user_id: str,
        is_archived: bool,
    ) -> ConversationRecord:
        with self._thread_write_lease(thread_id=root_thread_id):
            return self._lifecycle_coordinator().set_conversation_archive_state(
                root_thread_id=root_thread_id,
                user_id=user_id,
                is_archived=is_archived,
            )

    def archive_conversation(self, *, root_thread_id: str, user_id: str) -> ConversationRecord:
        return self._set_conversation_archive_state(
            root_thread_id=root_thread_id,
            user_id=user_id,
            is_archived=True,
        )

    def activate_conversation(self, *, root_thread_id: str, user_id: str) -> ConversationRecord:
        return self._set_conversation_archive_state(
            root_thread_id=root_thread_id,
            user_id=user_id,
            is_archived=False,
        )

    def prepare_merge_proposal(self, *, child_thread_id: str, user_id: str) -> MergeProposal:
        with self._thread_write_lease(thread_id=child_thread_id):
            return self._merge_coordinator().prepare_merge_proposal(
                child_thread_id=child_thread_id,
                user_id=user_id,
            )

    def apply_merge_decision(
        self,
        *,
        child_thread_id: str,
        decision: MergeDecision,
        context: RequestContext,
        proposal_overrides: MergeProposalOverrides | None = None,
    ) -> ImportedConclusion | None:
        self.repo.assert_thread_owner(thread_id=child_thread_id, owner_user_id=context.user_id)
        branch_record = self.repo.get_by_child_thread_id(child_thread_id)
        thread_ids = [child_thread_id]
        if decision.approved and decision.mode.value != 'none':
            target_thread_id = (
                branch_record.root_thread_id
                if decision.target == MergeTarget.ROOT_THREAD
                else branch_record.return_thread_id
            )
            thread_ids.append(target_thread_id)
        with self._thread_write_leases(thread_ids=thread_ids):
            return self._merge_coordinator().apply_merge_decision(
                child_thread_id=child_thread_id,
                decision=decision,
                context=context,
                proposal_overrides=proposal_overrides,
            )

    def get_branch_tree(self, *, root_thread_id: str, user_id: str) -> BranchTreeNode:
        return self._tree_coordinator().get_branch_tree(root_thread_id=root_thread_id, user_id=user_id)

    def list_archived_branches(self, *, root_thread_id: str, user_id: str) -> list[BranchTreeNode]:
        return self._tree_coordinator().list_archived_branches(root_thread_id=root_thread_id, user_id=user_id)

    def _set_branch_archive_state(self, *, child_thread_id: str, user_id: str, is_archived: bool) -> BranchRecord:
        with self._thread_write_lease(thread_id=child_thread_id):
            return self._tree_coordinator().set_branch_archive_state(
                child_thread_id=child_thread_id,
                user_id=user_id,
                is_archived=is_archived,
            )

    def archive_branch(self, *, child_thread_id: str, user_id: str) -> BranchRecord:
        return self._set_branch_archive_state(child_thread_id=child_thread_id, user_id=user_id, is_archived=True)

    def activate_branch(self, *, child_thread_id: str, user_id: str) -> BranchRecord:
        return self._set_branch_archive_state(child_thread_id=child_thread_id, user_id=user_id, is_archived=False)

from collections import defaultdict
from copy import deepcopy

from ...core.branching import BranchRecord, BranchRole, BranchStatus, BranchTreeNode


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

import logging
import uuid
from copy import deepcopy

from ...core.branching import BranchMeta, BranchRecord, BranchRole, BranchStatus
from ...core.types import ConversationRecord

logger = logging.getLogger("focus_agent.branches")


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
        parent_config = {"configurable": {"thread_id": parent_thread_id}}
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
            child_thread_id = copied["thread_id"]
            fork_strategy = "copy_thread"
        else:
            child_thread_id = str(uuid.uuid4())
            fork_strategy = "local_snapshot_seed"

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
        branch_meta_payload = branch_meta.model_dump(mode="json")
        branch_meta_payload["branch_name_pending_ai"] = branch_name is None
        branch_meta_payload["branch_role_pending_ai"] = (
            branch_role == BranchRole.EXPLORE_ALTERNATIVES
        )
        branch_meta_payload["branch_fork_message_count"] = len(
            list(parent_values.get("messages") or [])
        )
        if name_source is not None:
            branch_meta_payload["branch_name_source"] = name_source

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
        with svc._thread_write_lease(thread_id=child_thread_id):
            if fork_strategy == "local_snapshot_seed":
                svc.graph.update_state(
                    {"configurable": {"thread_id": child_thread_id}},
                    parent_values,
                    as_node="bootstrap_turn",
                )

            svc.graph.update_state(
                {"configurable": {"thread_id": child_thread_id}},
                {
                    "branch_meta": branch_meta_payload,
                    "merge_proposal": None,
                    "merge_decision": None,
                    "branch_local_findings": [],
                },
                as_node="bootstrap_turn",
            )
            svc.repo.ensure_thread_owner(
                thread_id=child_thread_id,
                root_thread_id=root_thread_id,
                owner_user_id=user_id,
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
        child_config = {"configurable": {"thread_id": child_thread_id}}
        child_snapshot = svc.graph.get_state(child_config)
        child_values = deepcopy(child_snapshot.values)
        existing_meta = dict(child_values.get("branch_meta") or {})
        if not force and not existing_meta.get("branch_role_pending_ai"):
            return branch_record

        next_role = svc._classify_branch_role(
            thread_values=child_values,
            current_role=branch_record.branch_role,
        )
        if next_role == branch_record.branch_role:
            return branch_record

        svc.repo.update_branch_role(branch_record.branch_id, next_role)
        updated_record = branch_record.model_copy(update={"branch_role": next_role})
        svc.graph.update_state(
            child_config,
            {"branch_meta": svc._branch_meta_payload_from_record(updated_record, existing_meta)},
            as_node="bootstrap_turn",
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

        child_config = {"configurable": {"thread_id": child_thread_id}}
        child_snapshot = svc.graph.get_state(child_config)
        child_values = deepcopy(child_snapshot.values)
        existing_meta = dict(child_values.get("branch_meta") or {})
        resolved_name_source = (
            name_source if name_source is not None else existing_meta.get("branch_name_source")
        )
        generated_name = svc._generate_branch_name(
            thread_values=child_values,
            branch_role=branch_record.branch_role,
            name_source=resolved_name_source,
        )
        next_name = svc._sanitize_branch_name(generated_name, branch_role=branch_record.branch_role)
        if not next_name or next_name == branch_record.branch_name:
            return branch_record

        svc.repo.update_branch_name(branch_record.branch_id, next_name)
        existing_meta = child_values.get("branch_meta") or {}
        updated_record = branch_record.model_copy(update={"branch_name": next_name})
        svc.graph.update_state(
            child_config,
            {"branch_meta": svc._branch_meta_payload_from_record(updated_record, existing_meta)},
            as_node="bootstrap_turn",
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
            child_config = {"configurable": {"thread_id": child_thread_id}}
            child_snapshot = svc.graph.get_state(child_config)
            child_values = deepcopy(child_snapshot.values)
            existing_meta = dict(child_values.get("branch_meta") or {})
            pending_name = bool(existing_meta.get("branch_name_pending_ai"))
            pending_role = bool(existing_meta.get("branch_role_pending_ai"))
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
            refreshed_meta = dict(refreshed_values.get("branch_meta") or {})
            refreshed_meta["branch_name_pending_ai"] = False
            refreshed_meta["branch_role_pending_ai"] = False
            svc.graph.update_state(
                child_config,
                {"branch_meta": refreshed_meta},
                as_node="bootstrap_turn",
            )
            return updated_record
        except (KeyError, PermissionError):
            raise
        except Exception:  # noqa: BLE001 - first-turn metadata refresh is best-effort
            logger.warning(
                "failed to refresh branch metadata after first turn",
                extra={"child_thread_id": child_thread_id},
                exc_info=True,
            )
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
        child_config = {"configurable": {"thread_id": child_thread_id}}
        snapshot = svc.graph.get_state(child_config)
        values = deepcopy(snapshot.values)
        updated_record = branch_record.model_copy(update={"branch_name": next_name})
        updated_meta = svc._branch_meta_payload_from_record(
            updated_record,
            existing_meta=dict(values.get("branch_meta") or {}),
        )
        updated_meta["branch_name_pending_ai"] = False
        svc.graph.update_state(
            child_config,
            {"branch_meta": updated_meta},
            as_node="bootstrap_turn",
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
            snapshot = svc.graph.get_state({"configurable": {"thread_id": root_thread_id}})
            values = deepcopy(getattr(snapshot, "values", {}) or {})
            generated_name = svc._generate_conversation_name(thread_values=values)
            next_title = svc._sanitize_branch_name(generated_name, branch_role=BranchRole.MAIN)
            return svc.repo.update_conversation_title(
                root_thread_id=root_thread_id,
                owner_user_id=user_id,
                title=next_title,
                title_pending_ai=False,
            )
        except (KeyError, PermissionError):
            raise
        except Exception:  # noqa: BLE001 - first-turn title refresh is best-effort
            logger.warning(
                "failed to refresh conversation title after first turn",
                extra={"root_thread_id": root_thread_id},
                exc_info=True,
            )
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

__all__ = ["BranchService"]
