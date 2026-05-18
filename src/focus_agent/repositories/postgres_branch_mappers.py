from __future__ import annotations

import json

from psycopg.types.json import Jsonb

from ..core.branching import BranchRecord
from ..core.types import ConversationRecord


class PostgresBranchMapperMixin:
    @staticmethod
    def _row_to_record(row: dict[str, object]) -> BranchRecord:
        return row_to_record(row)

    @staticmethod
    def _row_to_conversation(row: dict[str, object]) -> ConversationRecord:
        return row_to_conversation(row)

    @staticmethod
    def _default_conversation_title(root_thread_id: str) -> str:
        return default_conversation_title(root_thread_id)

    @staticmethod
    def _branch_params(record: BranchRecord) -> dict[str, object]:
        return branch_params(record)


def row_to_record(row: dict[str, object]) -> BranchRecord:
    return BranchRecord(
        branch_id=str(row["branch_id"]),
        root_thread_id=str(row["root_thread_id"]),
        parent_thread_id=str(row["parent_thread_id"]),
        child_thread_id=str(row["child_thread_id"]),
        return_thread_id=str(row["return_thread_id"]),
        owner_user_id=str(row["owner_user_id"]),
        branch_name=str(row["branch_name"]),
        branch_role=row["branch_role"],
        branch_depth=int(row["branch_depth"]),
        branch_status=row["branch_status"],
        is_archived=bool(row["is_archived"]),
        archived_at=optional_text(row.get("archived_at")),
        fork_checkpoint_id=optional_text(row.get("fork_checkpoint_id")),
        fork_strategy=str(row["fork_strategy"]),
        merge_proposal=json_to_dict(row.get("merge_proposal")),
        merge_decision=json_to_dict(row.get("merge_decision")),
    )


def row_to_conversation(row: dict[str, object]) -> ConversationRecord:
    return ConversationRecord(
        root_thread_id=str(row["root_thread_id"]),
        owner_user_id=str(row["owner_user_id"]),
        title=str(row["title"]),
        title_pending_ai=bool(row["title_pending_ai"]),
        is_archived=bool(row["is_archived"]),
        archived_at=optional_text(row.get("archived_at")),
        created_at=optional_text(row.get("created_at")),
        updated_at=optional_text(row.get("updated_at")),
    )


def default_conversation_title(root_thread_id: str) -> str:
    return "Main" if root_thread_id.endswith("-main") else root_thread_id


def branch_params(record: BranchRecord) -> dict[str, object]:
    return {
        "branch_id": record.branch_id,
        "root_thread_id": record.root_thread_id,
        "parent_thread_id": record.parent_thread_id,
        "child_thread_id": record.child_thread_id,
        "return_thread_id": record.return_thread_id,
        "owner_user_id": record.owner_user_id,
        "branch_name": record.branch_name,
        "branch_role": getattr(record.branch_role, "value", record.branch_role),
        "branch_depth": record.branch_depth,
        "branch_status": getattr(record.branch_status, "value", record.branch_status),
        "is_archived": record.is_archived,
        "archived_at": record.archived_at,
        "fork_checkpoint_id": record.fork_checkpoint_id,
        "fork_strategy": record.fork_strategy,
        "merge_proposal": Jsonb(record.merge_proposal)
        if record.merge_proposal is not None
        else None,
        "merge_decision": Jsonb(record.merge_decision)
        if record.merge_decision is not None
        else None,
    }


def branch_row_params(row: dict[str, object]) -> dict[str, object]:
    return {
        "branch_id": str(row["branch_id"]),
        "root_thread_id": str(row["root_thread_id"]),
        "parent_thread_id": str(row["parent_thread_id"]),
        "child_thread_id": str(row["child_thread_id"]),
        "return_thread_id": str(row["return_thread_id"]),
        "owner_user_id": str(row["owner_user_id"]),
        "branch_name": str(row["branch_name"]),
        "branch_role": str(row["branch_role"]),
        "branch_depth": int(row["branch_depth"]),
        "branch_status": str(row["branch_status"]),
        "is_archived": bool(row.get("is_archived", False)),
        "archived_at": row.get("archived_at"),
        "fork_checkpoint_id": row.get("fork_checkpoint_id"),
        "fork_strategy": str(row.get("fork_strategy") or "copy_thread"),
        "merge_proposal": Jsonb(row["merge_proposal"])
        if row.get("merge_proposal") is not None
        else None,
        "merge_decision": Jsonb(row["merge_decision"])
        if row.get("merge_decision") is not None
        else None,
    }


def optional_text(value: object) -> str | None:
    return None if value is None else str(value)


def json_to_dict(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    if isinstance(value, str):
        return dict(json.loads(value))
    return dict(value)
