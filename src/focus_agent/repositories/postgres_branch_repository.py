from __future__ import annotations

import json
from collections.abc import MutableSequence

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..core.branching import BranchRecord, BranchRole, BranchStatus, MergeDecision, MergeProposal
from ..core.types import ConversationRecord
from ..security.ownership import OwnershipAuditEvent, allow_ownership, deny_ownership
from .branch_repository import BranchRepository
from .postgres_schema import ensure_app_postgres_schema_on_connection


class PostgresBranchRepository(BranchRepository):
    def __init__(self, database_uri: str):
        self.database_uri = database_uri

    def setup(self) -> None:
        with psycopg.connect(self.database_uri) as conn:
            ensure_app_postgres_schema_on_connection(conn)

    def _connect(self):
        return psycopg.connect(self.database_uri, row_factory=dict_row)

    @staticmethod
    def _row_to_record(row: dict[str, object]) -> BranchRecord:
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
            archived_at=_optional_text(row.get("archived_at")),
            fork_checkpoint_id=_optional_text(row.get("fork_checkpoint_id")),
            fork_strategy=str(row["fork_strategy"]),
            merge_proposal=_json_to_dict(row.get("merge_proposal")),
            merge_decision=_json_to_dict(row.get("merge_decision")),
        )

    @staticmethod
    def _row_to_conversation(row: dict[str, object]) -> ConversationRecord:
        return ConversationRecord(
            root_thread_id=str(row["root_thread_id"]),
            owner_user_id=str(row["owner_user_id"]),
            title=str(row["title"]),
            title_pending_ai=bool(row["title_pending_ai"]),
            is_archived=bool(row["is_archived"]),
            archived_at=_optional_text(row.get("archived_at")),
            created_at=_optional_text(row.get("created_at")),
            updated_at=_optional_text(row.get("updated_at")),
        )

    @staticmethod
    def _default_conversation_title(root_thread_id: str) -> str:
        return "Main" if root_thread_id.endswith("-main") else root_thread_id

    def _backfill_conversations(self, *, owner_user_id: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT ta.root_thread_id
                    FROM focus_thread_access ta
                    LEFT JOIN focus_conversations c ON c.root_thread_id = ta.root_thread_id
                    WHERE ta.owner_user_id = %s
                      AND ta.thread_id = ta.root_thread_id
                      AND c.root_thread_id IS NULL
                    ORDER BY ta.created_at DESC, ta.root_thread_id DESC
                    """,
                    (owner_user_id,),
                )
                rows = cur.fetchall()
                for row in rows:
                    root_thread_id = str(row["root_thread_id"])
                    cur.execute(
                        """
                        INSERT INTO focus_conversations (
                            root_thread_id,
                            owner_user_id,
                            title,
                            title_pending_ai,
                            is_archived,
                            archived_at
                        )
                        VALUES (%s, %s, %s, %s, false, NULL)
                        ON CONFLICT (root_thread_id) DO NOTHING
                        """,
                        (
                            root_thread_id,
                            owner_user_id,
                            self._default_conversation_title(root_thread_id),
                            True,
                        ),
                    )

    def create(self, record: BranchRecord) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO focus_branches (
                        branch_id, root_thread_id, parent_thread_id, child_thread_id, return_thread_id,
                        owner_user_id, branch_name, branch_role, branch_depth, branch_status,
                        is_archived, archived_at, fork_checkpoint_id, fork_strategy,
                        merge_proposal, merge_decision
                    ) VALUES (
                        %(branch_id)s, %(root_thread_id)s, %(parent_thread_id)s, %(child_thread_id)s,
                        %(return_thread_id)s, %(owner_user_id)s, %(branch_name)s, %(branch_role)s,
                        %(branch_depth)s, %(branch_status)s, %(is_archived)s, %(archived_at)s,
                        %(fork_checkpoint_id)s, %(fork_strategy)s, %(merge_proposal)s, %(merge_decision)s
                    )
                    ON CONFLICT (branch_id) DO UPDATE SET
                        root_thread_id = EXCLUDED.root_thread_id,
                        parent_thread_id = EXCLUDED.parent_thread_id,
                        child_thread_id = EXCLUDED.child_thread_id,
                        return_thread_id = EXCLUDED.return_thread_id,
                        owner_user_id = EXCLUDED.owner_user_id,
                        branch_name = EXCLUDED.branch_name,
                        branch_role = EXCLUDED.branch_role,
                        branch_depth = EXCLUDED.branch_depth,
                        branch_status = EXCLUDED.branch_status,
                        is_archived = EXCLUDED.is_archived,
                        archived_at = EXCLUDED.archived_at,
                        fork_checkpoint_id = EXCLUDED.fork_checkpoint_id,
                        fork_strategy = EXCLUDED.fork_strategy,
                        merge_proposal = EXCLUDED.merge_proposal,
                        merge_decision = EXCLUDED.merge_decision,
                        updated_at = now()
                    """,
                    _branch_params(record),
                )

    def get(self, branch_id: str) -> BranchRecord:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM focus_branches WHERE branch_id = %s", (branch_id,))
                row = cur.fetchone()
        if row is None:
            raise KeyError(f"Unknown branch_id: {branch_id}")
        return self._row_to_record(row)

    def get_by_child_thread_id(self, child_thread_id: str) -> BranchRecord:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM focus_branches WHERE child_thread_id = %s", (child_thread_id,))
                row = cur.fetchone()
        if row is None:
            raise KeyError(f"Unknown child_thread_id: {child_thread_id}")
        return self._row_to_record(row)

    def list_by_root_thread_id(self, root_thread_id: str) -> list[BranchRecord]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM focus_branches
                    WHERE root_thread_id = %s
                    ORDER BY branch_depth, branch_name, child_thread_id
                    """,
                    (root_thread_id,),
                )
                rows = cur.fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_by_parent_thread_id(self, parent_thread_id: str) -> list[BranchRecord]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM focus_branches
                    WHERE parent_thread_id = %s
                    ORDER BY branch_name, child_thread_id
                    """,
                    (parent_thread_id,),
                )
                rows = cur.fetchall()
        return [self._row_to_record(row) for row in rows]

    def save_merge_proposal(self, branch_id: str, proposal: MergeProposal) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE focus_branches
                    SET merge_proposal = %s, updated_at = now()
                    WHERE branch_id = %s
                    """,
                    (Jsonb(proposal.model_dump(mode="json")), branch_id),
                )

    def save_merge_decision(self, branch_id: str, decision: MergeDecision) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE focus_branches
                    SET merge_decision = %s, updated_at = now()
                    WHERE branch_id = %s
                    """,
                    (Jsonb(decision.model_dump(mode="json")), branch_id),
                )

    def update_status(self, branch_id: str, status: BranchStatus) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE focus_branches
                    SET branch_status = %s, updated_at = now()
                    WHERE branch_id = %s
                    """,
                    (status.value, branch_id),
                )

    def update_archive_state(self, branch_id: str, *, is_archived: bool) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE focus_branches
                    SET is_archived = %s,
                        archived_at = CASE WHEN %s THEN now() ELSE NULL END,
                        updated_at = now()
                    WHERE branch_id = %s
                    """,
                    (is_archived, is_archived, branch_id),
                )

    def update_branch_name(self, branch_id: str, branch_name: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE focus_branches
                    SET branch_name = %s, updated_at = now()
                    WHERE branch_id = %s
                    """,
                    (branch_name, branch_id),
                )

    def update_branch_role(self, branch_id: str, branch_role: BranchRole) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE focus_branches
                    SET branch_role = %s, updated_at = now()
                    WHERE branch_id = %s
                    """,
                    (branch_role.value, branch_id),
                )

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
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO focus_thread_access (thread_id, root_thread_id, owner_user_id)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (thread_id) DO NOTHING
                    """,
                    (thread_id, root_thread_id, owner_user_id),
                )
                cur.execute(
                    "SELECT owner_user_id FROM focus_thread_access WHERE thread_id = %s",
                    (thread_id,),
                )
                existing = cur.fetchone()
                if existing is None or str(existing["owner_user_id"]) != owner_user_id:
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
            reason="thread_owner_registered_or_matched",
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
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT owner_user_id FROM focus_thread_access WHERE thread_id = %s",
                    (thread_id,),
                )
                row = cur.fetchone()
        if row is None:
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
        if str(row["owner_user_id"]) != owner_user_id:
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
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT owner_user_id FROM focus_thread_access WHERE thread_id = %s",
                    (thread_id,),
                )
                row = cur.fetchone()
        return None if row is None else str(row["owner_user_id"])

    def create_conversation(self, record: ConversationRecord) -> ConversationRecord:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO focus_conversations (
                        root_thread_id,
                        owner_user_id,
                        title,
                        title_pending_ai,
                        is_archived,
                        archived_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (root_thread_id) DO UPDATE SET
                        owner_user_id = EXCLUDED.owner_user_id,
                        title = EXCLUDED.title,
                        title_pending_ai = EXCLUDED.title_pending_ai,
                        is_archived = EXCLUDED.is_archived,
                        archived_at = EXCLUDED.archived_at,
                        updated_at = now()
                    """,
                    (
                        record.root_thread_id,
                        record.owner_user_id,
                        record.title,
                        record.title_pending_ai,
                        record.is_archived,
                        record.archived_at,
                    ),
                )
        return self.get_conversation(record.root_thread_id)

    def get_conversation(self, root_thread_id: str) -> ConversationRecord:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM focus_conversations WHERE root_thread_id = %s",
                    (root_thread_id,),
                )
                row = cur.fetchone()
        if row is None:
            raise KeyError(f"Unknown root_thread_id: {root_thread_id}")
        return self._row_to_conversation(row)

    def list_conversations(self, *, owner_user_id: str) -> list[ConversationRecord]:
        self._backfill_conversations(owner_user_id=owner_user_id)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM focus_conversations
                    WHERE owner_user_id = %s
                    ORDER BY is_archived ASC, created_at DESC, root_thread_id DESC
                    """,
                    (owner_user_id,),
                )
                rows = cur.fetchall()
        return [self._row_to_conversation(row) for row in rows]

    def update_conversation_title(
        self,
        *,
        root_thread_id: str,
        owner_user_id: str,
        title: str,
        title_pending_ai: bool | None = None,
    ) -> ConversationRecord:
        self._backfill_conversations(owner_user_id=owner_user_id)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT owner_user_id FROM focus_conversations WHERE root_thread_id = %s",
                    (root_thread_id,),
                )
                row = cur.fetchone()
                if row is None:
                    raise KeyError(f"Unknown root_thread_id: {root_thread_id}")
                if str(row["owner_user_id"]) != owner_user_id:
                    raise PermissionError(
                        f"User {owner_user_id} cannot update conversation {root_thread_id}."
                    )
                if title_pending_ai is None:
                    cur.execute(
                        """
                        UPDATE focus_conversations
                        SET title = %s, updated_at = now()
                        WHERE root_thread_id = %s
                        """,
                        (title, root_thread_id),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE focus_conversations
                        SET title = %s, title_pending_ai = %s, updated_at = now()
                        WHERE root_thread_id = %s
                        """,
                        (title, title_pending_ai, root_thread_id),
                    )
        return self.get_conversation(root_thread_id)

    def update_conversation_archive_state(
        self,
        *,
        root_thread_id: str,
        owner_user_id: str,
        is_archived: bool,
    ) -> ConversationRecord:
        self._backfill_conversations(owner_user_id=owner_user_id)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT owner_user_id FROM focus_conversations WHERE root_thread_id = %s",
                    (root_thread_id,),
                )
                row = cur.fetchone()
                if row is None:
                    raise KeyError(f"Unknown root_thread_id: {root_thread_id}")
                if str(row["owner_user_id"]) != owner_user_id:
                    raise PermissionError(
                        f"User {owner_user_id} cannot update conversation {root_thread_id}."
                    )
                cur.execute(
                    """
                    UPDATE focus_conversations
                    SET is_archived = %s,
                        archived_at = CASE WHEN %s THEN now() ELSE NULL END,
                        updated_at = now()
                    WHERE root_thread_id = %s
                    """,
                    (is_archived, is_archived, root_thread_id),
                )
        return self.get_conversation(root_thread_id)

    def upsert_thread_access_rows(self, rows: list[dict[str, object]]) -> int:
        if not rows:
            return 0
        with self._connect() as conn:
            with conn.cursor() as cur:
                for row in rows:
                    cur.execute(
                        """
                        INSERT INTO focus_thread_access (
                            thread_id,
                            root_thread_id,
                            owner_user_id,
                            created_at
                        )
                        VALUES (%s, %s, %s, COALESCE(%s, now()))
                        ON CONFLICT (thread_id) DO UPDATE SET
                            root_thread_id = EXCLUDED.root_thread_id,
                            owner_user_id = EXCLUDED.owner_user_id
                        """,
                        (
                            str(row["thread_id"]),
                            str(row["root_thread_id"]),
                            str(row["owner_user_id"]),
                            row.get("created_at"),
                        ),
                    )
        return len(rows)

    def upsert_conversation_rows(self, rows: list[dict[str, object]]) -> int:
        if not rows:
            return 0
        with self._connect() as conn:
            with conn.cursor() as cur:
                for row in rows:
                    cur.execute(
                        """
                        INSERT INTO focus_conversations (
                            root_thread_id,
                            owner_user_id,
                            title,
                            title_pending_ai,
                            is_archived,
                            archived_at,
                            created_at,
                            updated_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, COALESCE(%s, now()), COALESCE(%s, now()))
                        ON CONFLICT (root_thread_id) DO UPDATE SET
                            owner_user_id = EXCLUDED.owner_user_id,
                            title = EXCLUDED.title,
                            title_pending_ai = EXCLUDED.title_pending_ai,
                            is_archived = EXCLUDED.is_archived,
                            archived_at = EXCLUDED.archived_at,
                            updated_at = COALESCE(EXCLUDED.updated_at, now())
                        """,
                        (
                            str(row["root_thread_id"]),
                            str(row["owner_user_id"]),
                            str(row["title"]),
                            bool(row.get("title_pending_ai", False)),
                            bool(row.get("is_archived", False)),
                            row.get("archived_at"),
                            row.get("created_at"),
                            row.get("updated_at"),
                        ),
                    )
        return len(rows)

    def upsert_branch_rows(self, rows: list[dict[str, object]]) -> int:
        if not rows:
            return 0
        with self._connect() as conn:
            with conn.cursor() as cur:
                for row in rows:
                    payload = {
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
                        "merge_proposal": Jsonb(row["merge_proposal"]) if row.get("merge_proposal") is not None else None,
                        "merge_decision": Jsonb(row["merge_decision"]) if row.get("merge_decision") is not None else None,
                    }
                    cur.execute(
                        """
                        INSERT INTO focus_branches (
                            branch_id, root_thread_id, parent_thread_id, child_thread_id, return_thread_id,
                            owner_user_id, branch_name, branch_role, branch_depth, branch_status,
                            is_archived, archived_at, fork_checkpoint_id, fork_strategy,
                            merge_proposal, merge_decision
                        ) VALUES (
                            %(branch_id)s, %(root_thread_id)s, %(parent_thread_id)s, %(child_thread_id)s,
                            %(return_thread_id)s, %(owner_user_id)s, %(branch_name)s, %(branch_role)s,
                            %(branch_depth)s, %(branch_status)s, %(is_archived)s, %(archived_at)s,
                            %(fork_checkpoint_id)s, %(fork_strategy)s, %(merge_proposal)s, %(merge_decision)s
                        )
                        ON CONFLICT (branch_id) DO UPDATE SET
                            root_thread_id = EXCLUDED.root_thread_id,
                            parent_thread_id = EXCLUDED.parent_thread_id,
                            child_thread_id = EXCLUDED.child_thread_id,
                            return_thread_id = EXCLUDED.return_thread_id,
                            owner_user_id = EXCLUDED.owner_user_id,
                            branch_name = EXCLUDED.branch_name,
                            branch_role = EXCLUDED.branch_role,
                            branch_depth = EXCLUDED.branch_depth,
                            branch_status = EXCLUDED.branch_status,
                            is_archived = EXCLUDED.is_archived,
                            archived_at = EXCLUDED.archived_at,
                            fork_checkpoint_id = EXCLUDED.fork_checkpoint_id,
                            fork_strategy = EXCLUDED.fork_strategy,
                            merge_proposal = EXCLUDED.merge_proposal,
                            merge_decision = EXCLUDED.merge_decision,
                            updated_at = now()
                        """,
                        payload,
                    )
        return len(rows)


def create_local_state_migration_sink(database_uri: str) -> PostgresBranchRepository:
    return PostgresBranchRepository(database_uri)


def _branch_params(record: BranchRecord) -> dict[str, object]:
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
        "merge_proposal": Jsonb(record.merge_proposal) if record.merge_proposal is not None else None,
        "merge_decision": Jsonb(record.merge_decision) if record.merge_decision is not None else None,
    }


def _optional_text(value: object) -> str | None:
    return None if value is None else str(value)


def _json_to_dict(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    if isinstance(value, str):
        return dict(json.loads(value))
    return dict(value)
