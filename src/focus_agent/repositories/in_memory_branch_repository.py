from __future__ import annotations

from datetime import UTC, datetime
from threading import RLock
from typing import MutableSequence

from ..core.branching import BranchRecord, BranchRole, BranchStatus, MergeDecision, MergeProposal
from ..core.types import ConversationRecord
from ..security.ownership import (
    OwnershipAuditEvent,
    allow_ownership,
    deny_ownership,
)
from .branch_repository import BranchRepository


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class InMemoryBranchRepository(BranchRepository):
    def __init__(self) -> None:
        self._lock = RLock()
        self._branches: dict[str, BranchRecord] = {}
        self._thread_access: dict[str, str] = {}
        self._thread_roots: dict[str, str] = {}
        self._conversations: dict[str, ConversationRecord] = {}

    @staticmethod
    def _default_conversation_title(root_thread_id: str) -> str:
        return "Main" if root_thread_id.endswith("-main") else root_thread_id

    @staticmethod
    def _copy_branch(record: BranchRecord) -> BranchRecord:
        return record.model_copy(deep=True)

    @staticmethod
    def _copy_conversation(record: ConversationRecord) -> ConversationRecord:
        return record.model_copy(deep=True)

    @staticmethod
    def _row_to_record(record: BranchRecord) -> BranchRecord:
        return record

    @staticmethod
    def _row_to_conversation(record: ConversationRecord) -> ConversationRecord:
        return record

    def _backfill_conversations(self, *, owner_user_id: str) -> None:
        for thread_id, owner in list(self._thread_roots.items()):
            if owner != owner_user_id:
                continue
            root_thread_id = self._thread_roots[thread_id]
            if thread_id != root_thread_id:
                continue
            if root_thread_id in self._conversations:
                continue
            self._conversations[root_thread_id] = ConversationRecord(
                root_thread_id=root_thread_id,
                owner_user_id=owner_user_id,
                title=self._default_conversation_title(root_thread_id),
                title_pending_ai=True,
                is_archived=False,
                archived_at=None,
                created_at=_now_iso(),
                updated_at=_now_iso(),
                token_usage={},
            )

    def create(self, record: BranchRecord) -> None:
        with self._lock:
            if record.branch_id in self._branches:
                raise ValueError(f"branch_id already exists: {record.branch_id}")
            self._branches[record.branch_id] = self._copy_branch(record)

    def get(self, branch_id: str) -> BranchRecord:
        with self._lock:
            record = self._branches.get(branch_id)
        if record is None:
            raise KeyError(f"Unknown branch_id: {branch_id}")
        return self._row_to_record(record)

    def get_by_child_thread_id(self, child_thread_id: str) -> BranchRecord:
        with self._lock:
            matches = [record for record in self._branches.values() if record.child_thread_id == child_thread_id]
        if not matches:
            raise KeyError(f"Unknown child_thread_id: {child_thread_id}")
        return self._row_to_record(matches[0])

    def list_by_root_thread_id(self, root_thread_id: str) -> list[BranchRecord]:
        with self._lock:
            matches = [record for record in self._branches.values() if record.root_thread_id == root_thread_id]
        matches.sort(key=lambda item: (item.branch_depth, item.branch_name, item.child_thread_id))
        return [self._row_to_record(item) for item in matches]

    def list_by_parent_thread_id(self, parent_thread_id: str) -> list[BranchRecord]:
        with self._lock:
            matches = [record for record in self._branches.values() if record.parent_thread_id == parent_thread_id]
        matches.sort(key=lambda item: (item.branch_name, item.child_thread_id))
        return [self._row_to_record(item) for item in matches]

    def save_merge_proposal(self, branch_id: str, proposal: MergeProposal) -> None:
        with self._lock:
            record = self._branches.get(branch_id)
            if record is None:
                raise KeyError(f"Unknown branch_id: {branch_id}")
            self._branches[branch_id] = record.model_copy(update={"merge_proposal": proposal.model_dump()})

    def save_merge_decision(self, branch_id: str, decision: MergeDecision) -> None:
        with self._lock:
            record = self._branches.get(branch_id)
            if record is None:
                raise KeyError(f"Unknown branch_id: {branch_id}")
            self._branches[branch_id] = record.model_copy(update={"merge_decision": decision.model_dump()})

    def update_status(self, branch_id: str, status: BranchStatus) -> None:
        with self._lock:
            record = self._branches.get(branch_id)
            if record is None:
                raise KeyError(f"Unknown branch_id: {branch_id}")
            self._branches[branch_id] = record.model_copy(update={"branch_status": status})

    def update_archive_state(self, branch_id: str, *, is_archived: bool) -> None:
        with self._lock:
            record = self._branches.get(branch_id)
            if record is None:
                raise KeyError(f"Unknown branch_id: {branch_id}")
            self._branches[branch_id] = record.model_copy(
                update={
                    "is_archived": bool(is_archived),
                    "archived_at": _now_iso() if is_archived else None,
                }
            )

    def update_branch_name(self, branch_id: str, branch_name: str) -> None:
        with self._lock:
            record = self._branches.get(branch_id)
            if record is None:
                raise KeyError(f"Unknown branch_id: {branch_id}")
            self._branches[branch_id] = record.model_copy(update={"branch_name": branch_name})

    def update_branch_role(self, branch_id: str, branch_role: BranchRole) -> None:
        with self._lock:
            record = self._branches.get(branch_id)
            if record is None:
                raise KeyError(f"Unknown branch_id: {branch_id}")
            self._branches[branch_id] = record.model_copy(update={"branch_role": branch_role})

    def ensure_thread_owner(
        self,
        *,
        thread_id: str,
        root_thread_id: str,
        owner_user_id: str,
        audit_events: MutableSequence[OwnershipAuditEvent] | None = None,
        request_id: str | None = None,
    ) -> None:
        events = audit_events if audit_events is not None else []
        with self._lock:
            existing_owner = self._thread_access.get(thread_id)
            existing_root = self._thread_roots.get(thread_id)
            if existing_owner is None:
                self._thread_access[thread_id] = owner_user_id
                self._thread_roots[thread_id] = root_thread_id
                self._backfill_conversations(owner_user_id=owner_user_id)
                allow_ownership(
                    events,
                    principal=owner_user_id,
                    resource_type="thread",
                    resource_id=thread_id,
                    action="access",
                    reason="thread_owner_registered",
                    request_id=request_id,
                )
                return

            if existing_root != root_thread_id and existing_root is not None:
                self._thread_roots[thread_id] = existing_root
            if existing_owner != owner_user_id:
                deny_ownership(
                    events,
                    principal=owner_user_id,
                    resource_type="thread",
                    resource_id=thread_id,
                    action="access",
                    reason="owner_mismatch",
                    request_id=request_id,
                )

            allow_ownership(
                events,
                principal=owner_user_id,
                resource_type="thread",
                resource_id=thread_id,
                action="access",
                reason="owner_match",
                request_id=request_id,
            )

    def assert_thread_owner(
        self,
        *,
        thread_id: str,
        owner_user_id: str,
        audit_events: MutableSequence[OwnershipAuditEvent] | None = None,
        request_id: str | None = None,
    ) -> None:
        events = audit_events if audit_events is not None else []
        with self._lock:
            owner = self._thread_access.get(thread_id)
        if owner is None:
            deny_ownership(
                events,
                principal=owner_user_id,
                resource_type="thread",
                resource_id=thread_id,
                action="access",
                reason="thread_unregistered",
                request_id=request_id,
                message=f"Thread {thread_id} is not registered for access yet.",
            )
        if owner != owner_user_id:
            deny_ownership(
                events,
                principal=owner_user_id,
                resource_type="thread",
                resource_id=thread_id,
                action="access",
                reason="owner_mismatch",
                request_id=request_id,
            )
        allow_ownership(
            events,
            principal=owner_user_id,
            resource_type="thread",
            resource_id=thread_id,
            action="access",
            reason="owner_match",
            request_id=request_id,
        )

    def get_thread_owner(self, *, thread_id: str) -> str | None:
        with self._lock:
            return self._thread_access.get(thread_id)

    def create_conversation(self, record: ConversationRecord) -> ConversationRecord:
        with self._lock:
            if record.root_thread_id in self._conversations:
                raise ValueError(f"Conversation already exists: {record.root_thread_id}")
            created = record.model_copy(
                update={
                    "created_at": record.created_at or _now_iso(),
                    "updated_at": record.updated_at or _now_iso(),
                }
            )
            self._conversations[record.root_thread_id] = created
        return self.get_conversation(record.root_thread_id)

    def get_conversation(self, root_thread_id: str) -> ConversationRecord:
        with self._lock:
            record = self._conversations.get(root_thread_id)
        if record is None:
            raise KeyError(f"Unknown root_thread_id: {root_thread_id}")
        return self._row_to_conversation(record)

    def list_conversations(self, *, owner_user_id: str) -> list[ConversationRecord]:
        self._backfill_conversations(owner_user_id=owner_user_id)
        with self._lock:
            records = [
                record
                for record in self._conversations.values()
                if record.owner_user_id == owner_user_id
            ]
        records.sort(
            key=lambda item: (item.is_archived, item.created_at or "", item.root_thread_id),
            reverse=True,
        )
        records.sort(key=lambda item: item.is_archived)
        return [self._row_to_conversation(record) for record in records]

    def update_conversation_title(
        self,
        *,
        root_thread_id: str,
        owner_user_id: str,
        title: str,
        title_pending_ai: bool | None = None,
    ) -> ConversationRecord:
        self._backfill_conversations(owner_user_id=owner_user_id)
        with self._lock:
            record = self._conversations.get(root_thread_id)
            if record is None:
                raise KeyError(f"Unknown root_thread_id: {root_thread_id}")
            if record.owner_user_id != owner_user_id:
                raise PermissionError(
                    f"User {owner_user_id} cannot update conversation {root_thread_id}."
                )
            updates: dict[str, object] = {
                "title": title,
                "updated_at": _now_iso(),
            }
            if title_pending_ai is not None:
                updates["title_pending_ai"] = bool(title_pending_ai)
            self._conversations[root_thread_id] = record.model_copy(update=updates)
            updated = self._conversations[root_thread_id]
        return self._row_to_conversation(updated)

    def update_conversation_archive_state(
        self,
        *,
        root_thread_id: str,
        owner_user_id: str,
        is_archived: bool,
    ) -> ConversationRecord:
        self._backfill_conversations(owner_user_id=owner_user_id)
        with self._lock:
            record = self._conversations.get(root_thread_id)
            if record is None:
                raise KeyError(f"Unknown root_thread_id: {root_thread_id}")
            if record.owner_user_id != owner_user_id:
                raise PermissionError(
                    f"User {owner_user_id} cannot update conversation {root_thread_id}."
                )
            archived = bool(is_archived)
            self._conversations[root_thread_id] = record.model_copy(
                update={
                    "is_archived": archived,
                    "archived_at": _now_iso() if archived else None,
                    "updated_at": _now_iso(),
                }
            )
            updated = self._conversations[root_thread_id]
        return self._row_to_conversation(updated)


__all__ = ["InMemoryBranchRepository"]
