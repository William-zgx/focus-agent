from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import MutableSequence

from ..core.branching import BranchRecord, BranchRole, BranchStatus, MergeDecision, MergeProposal
from ..core.types import ConversationRecord
from ..security.ownership import (
    OwnershipAuditEvent,
    OwnershipAuditExport,
    export_ownership_audit_events,
)


class BranchRepository(ABC):
    def export_ownership_audit_events(
        self,
        audit_events: MutableSequence[OwnershipAuditEvent],
    ) -> list[OwnershipAuditExport]:
        return export_ownership_audit_events(audit_events)

    @abstractmethod
    def create(self, record: BranchRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def get(self, branch_id: str) -> BranchRecord:
        raise NotImplementedError

    @abstractmethod
    def get_by_child_thread_id(self, child_thread_id: str) -> BranchRecord:
        raise NotImplementedError

    @abstractmethod
    def list_by_root_thread_id(self, root_thread_id: str) -> list[BranchRecord]:
        raise NotImplementedError

    @abstractmethod
    def list_by_parent_thread_id(self, parent_thread_id: str) -> list[BranchRecord]:
        raise NotImplementedError

    @abstractmethod
    def save_merge_proposal(self, branch_id: str, proposal: MergeProposal) -> None:
        raise NotImplementedError

    @abstractmethod
    def save_merge_decision(self, branch_id: str, decision: MergeDecision) -> None:
        raise NotImplementedError

    @abstractmethod
    def update_status(self, branch_id: str, status: BranchStatus) -> None:
        raise NotImplementedError

    @abstractmethod
    def update_archive_state(self, branch_id: str, *, is_archived: bool) -> None:
        raise NotImplementedError

    @abstractmethod
    def update_branch_name(self, branch_id: str, branch_name: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def update_branch_role(self, branch_id: str, branch_role: BranchRole) -> None:
        raise NotImplementedError

    @abstractmethod
    def ensure_thread_owner(
        self,
        *,
        thread_id: str,
        root_thread_id: str,
        owner_user_id: str,
        audit_events: MutableSequence[OwnershipAuditEvent] | None = None,
        request_id: str | None = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def assert_thread_owner(
        self,
        *,
        thread_id: str,
        owner_user_id: str,
        audit_events: MutableSequence[OwnershipAuditEvent] | None = None,
        request_id: str | None = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_thread_owner(self, *, thread_id: str) -> str | None:
        raise NotImplementedError

    @abstractmethod
    def create_conversation(self, record: ConversationRecord) -> ConversationRecord:
        raise NotImplementedError

    @abstractmethod
    def get_conversation(self, root_thread_id: str) -> ConversationRecord:
        raise NotImplementedError

    @abstractmethod
    def list_conversations(self, *, owner_user_id: str) -> list[ConversationRecord]:
        raise NotImplementedError

    @abstractmethod
    def update_conversation_title(
        self,
        *,
        root_thread_id: str,
        owner_user_id: str,
        title: str,
        title_pending_ai: bool | None = None,
    ) -> ConversationRecord:
        raise NotImplementedError

    @abstractmethod
    def update_conversation_archive_state(
        self,
        *,
        root_thread_id: str,
        owner_user_id: str,
        is_archived: bool,
    ) -> ConversationRecord:
        raise NotImplementedError
