from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager

from langgraph_sdk import get_sync_client

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
    ThreadResolution,
)
from ...core.merge_review import (
    generate_merge_proposal,  # noqa: F401 - compatibility monkeypatch hook
)
from ...core.request_context import RequestContext
from ...core.types import ConversationRecord
from ...memory import MemoryWriter
from ...model_registry import create_chat_model as _default_create_chat_model
from ...repositories.branch_repository import BranchRepository
from ..coordination import CoordinationBackend, create_in_memory_coordination_backend
from ..thread_turn_lease import ThreadTurnLeaseManager
from .actions import BranchNamingPolicyMixin
from .lifecycle import BranchLifecycleCoordinator
from .merge import BranchMemoryPromotionMixin, BranchMergeCoordinator
from .tree import BranchTreeCoordinator

logger = logging.getLogger("focus_agent.branches")


def create_chat_model(*args, **kwargs):
    package = sys.modules.get("focus_agent.services.branches")
    patched = getattr(package, "create_chat_model", None) if package is not None else None
    if patched is not None and patched is not create_chat_model:
        return patched(*args, **kwargs)
    return _default_create_chat_model(*args, **kwargs)


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
        self.thread_client = (
            get_sync_client(url=settings.langgraph_api_url) if settings.langgraph_api_url else None
        )
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
        configured_seconds = float(
            getattr(settings, "runtime_thread_lock_heartbeat_seconds", 30.0) or 30.0
        )
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
    def _thread_write_leases(
        self, *, thread_ids: list[str] | tuple[str, ...] | set[str]
    ) -> Iterator[None]:
        ordered_thread_ids = sorted(
            {str(thread_id) for thread_id in thread_ids if str(thread_id).strip()}
        )
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

        proposal_payload = proposal.model_dump(mode="json")
        override_payload = overrides.model_dump(exclude_none=True, mode="json")
        if "summary" in override_payload:
            override_payload["summary"] = str(override_payload["summary"]).strip()
        for key in ("key_findings", "open_questions", "evidence_refs", "artifacts"):
            if key in override_payload:
                override_payload[key] = self._clean_list_override(override_payload[key])

        merged = MergeProposal.model_validate({**proposal_payload, **override_payload})
        if not merged.summary.strip():
            raise ValueError("Merge proposal summary cannot be empty.")
        return merged

    def _derive_root_thread_id(self, parent_thread_id: str, parent_state: dict) -> str:
        meta = parent_state.get("branch_meta") or {}
        root_thread_id = meta.get("root_thread_id")
        if root_thread_id:
            return str(root_thread_id)
        return self._resolve_thread_ref(thread_id=parent_thread_id).root_thread_id

    def _derive_parent_branch_depth(self, parent_thread_id: str, parent_state: dict) -> int:
        meta = parent_state.get("branch_meta") or {}
        if meta.get("branch_depth") is not None:
            return int(meta.get("branch_depth") or 0)
        try:
            record = self.repo.get_by_child_thread_id(parent_thread_id)
        except KeyError:
            return 0
        return record.branch_depth

    def _derive_parent_branch_status(
        self, parent_thread_id: str, parent_state: dict
    ) -> BranchStatus | None:
        try:
            record = self.repo.get_by_child_thread_id(parent_thread_id)
        except KeyError:
            record = None
        if record is not None:
            return record.branch_status
        meta = parent_state.get("branch_meta") or {}
        raw_status = meta.get("branch_status")
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
    def _branch_meta_payload_from_record(
        record: BranchRecord, existing_meta: dict | None = None
    ) -> dict[str, object]:
        payload = dict(existing_meta or {})
        payload.pop("conclusion_policy", None)
        payload.update(
            {
                "branch_id": record.branch_id,
                "root_thread_id": record.root_thread_id,
                "parent_thread_id": record.parent_thread_id,
                "return_thread_id": record.return_thread_id,
                "branch_name": record.branch_name,
                "branch_role": record.branch_role.value,
                "branch_depth": record.branch_depth,
                "branch_status": record.branch_status.value,
                "is_archived": record.is_archived,
                "archived_at": record.archived_at,
                "fork_checkpoint_id": record.fork_checkpoint_id,
                "fork_strategy": record.fork_strategy,
            }
        )
        return payload

    def _build_tree_node(
        self, record: BranchRecord, by_parent: dict[str, list[BranchRecord]]
    ) -> BranchTreeNode:
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
            children=[
                self._build_tree_node(child, by_parent)
                for child in by_parent.get(record.child_thread_id, [])
            ],
        )

    def _ensure_root_thread_access(self, *, root_thread_id: str, user_id: str) -> None:
        resolution = self._resolve_thread_ref(thread_id=root_thread_id, user_id=user_id)
        if not resolution.is_root:
            root_thread_id = resolution.root_thread_id
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
        resolution = self._resolve_thread_ref(thread_id=parent_thread_id, user_id=user_id)
        if resolution.is_root:
            self._ensure_root_thread_access(
                root_thread_id=resolution.root_thread_id, user_id=user_id
            )
            return
        self.repo.assert_thread_owner(thread_id=parent_thread_id, owner_user_id=user_id)

    def _resolve_thread_ref(
        self, *, thread_id: str, user_id: str | None = None
    ) -> ThreadResolution:
        resolver = getattr(self.repo, "resolve_thread_ref", None)
        if callable(resolver):
            return resolver(thread_id=thread_id, owner_user_id=user_id)
        try:
            record = self.repo.get_by_child_thread_id(thread_id)
        except KeyError:
            return ThreadResolution(
                input_thread_id=thread_id,
                root_thread_id=thread_id,
                source_thread_id=thread_id,
                diagnostic="resolver_unavailable_assumed_root",
            )
        return ThreadResolution(
            input_thread_id=thread_id,
            root_thread_id=record.root_thread_id,
            source_thread_id=record.child_thread_id,
            branch_id=record.branch_id,
            is_root=False,
            branch_status=record.branch_status,
            diagnostic="resolver_unavailable_child_lookup",
        )

    def _is_registered_root_thread(self, root_thread_id: str) -> bool:
        get_owner = getattr(self.repo, "get_thread_owner", None)
        if callable(get_owner) and get_owner(thread_id=root_thread_id) is not None:
            return True
        get_conversation = getattr(self.repo, "get_conversation", None)
        if not callable(get_conversation):
            return False
        try:
            get_conversation(root_thread_id)
        except Exception:
            return False
        return True

    def _require_child_branch_record(
        self,
        *,
        child_thread_id: str,
        user_id: str | None = None,
        operation: str = "Branch operation",
    ) -> BranchRecord:
        try:
            record = self.repo.get_by_child_thread_id(child_thread_id)
        except KeyError as exc:
            resolution = self._resolve_thread_ref(thread_id=child_thread_id, user_id=user_id)
            if resolution.is_root and self._is_registered_root_thread(resolution.root_thread_id):
                raise ValueError(
                    f"{operation} requires a child_thread_id, but {child_thread_id} "
                    f"resolves to root thread {resolution.root_thread_id}."
                ) from exc
            raise
        if user_id is not None:
            self.repo.assert_thread_owner(thread_id=child_thread_id, owner_user_id=user_id)
        return record

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
        branch_record = self._require_child_branch_record(
            child_thread_id=child_thread_id,
            user_id=context.user_id,
            operation="Applying a merge decision",
        )
        thread_ids = [child_thread_id]
        if decision.approved and decision.mode.value != "none":
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
        return self._tree_coordinator().get_branch_tree(
            root_thread_id=root_thread_id, user_id=user_id
        )

    def list_archived_branches(self, *, root_thread_id: str, user_id: str) -> list[BranchTreeNode]:
        return self._tree_coordinator().list_archived_branches(
            root_thread_id=root_thread_id, user_id=user_id
        )

    def _set_branch_archive_state(
        self, *, child_thread_id: str, user_id: str, is_archived: bool
    ) -> BranchRecord:
        with self._thread_write_lease(thread_id=child_thread_id):
            return self._tree_coordinator().set_branch_archive_state(
                child_thread_id=child_thread_id,
                user_id=user_id,
                is_archived=is_archived,
            )

    def archive_branch(self, *, child_thread_id: str, user_id: str) -> BranchRecord:
        return self._set_branch_archive_state(
            child_thread_id=child_thread_id, user_id=user_id, is_archived=True
        )

    def activate_branch(self, *, child_thread_id: str, user_id: str) -> BranchRecord:
        return self._set_branch_archive_state(
            child_thread_id=child_thread_id, user_id=user_id, is_archived=False
        )



__all__ = ["BranchService", "create_chat_model"]
