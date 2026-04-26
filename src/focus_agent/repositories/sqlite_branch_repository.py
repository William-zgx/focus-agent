from __future__ import annotations

import json
import sqlite3
from collections.abc import MutableSequence
from pathlib import Path

from ..core.branching import BranchRecord, BranchRole, BranchStatus, MergeDecision, MergeProposal
from ..core.types import ConversationRecord
from ..security.ownership import OwnershipAuditEvent, allow_ownership, deny_ownership
from .branch_repository import BranchRepository


class SQLiteBranchRepository(BranchRepository):
    def __init__(self, db_path: str):
        self.db_path = str(Path(db_path).expanduser())
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._setup()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _setup(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS branches (
                    branch_id TEXT PRIMARY KEY,
                    root_thread_id TEXT NOT NULL,
                    parent_thread_id TEXT NOT NULL,
                    child_thread_id TEXT NOT NULL UNIQUE,
                    return_thread_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
                    branch_name TEXT NOT NULL,
                    branch_role TEXT NOT NULL,
                    branch_depth INTEGER NOT NULL,
                    branch_status TEXT NOT NULL,
                    is_archived INTEGER NOT NULL DEFAULT 0,
                    archived_at TEXT,
                    fork_checkpoint_id TEXT,
                    fork_strategy TEXT NOT NULL,
                    merge_proposal_json TEXT,
                    merge_decision_json TEXT
                )
                """
            )
            columns = {row['name'] for row in conn.execute('PRAGMA table_info(branches)').fetchall()}
            if 'owner_user_id' not in columns:
                conn.execute("ALTER TABLE branches ADD COLUMN owner_user_id TEXT NOT NULL DEFAULT 'unknown'")
            if 'is_archived' not in columns:
                conn.execute("ALTER TABLE branches ADD COLUMN is_archived INTEGER NOT NULL DEFAULT 0")
            if 'archived_at' not in columns:
                conn.execute("ALTER TABLE branches ADD COLUMN archived_at TEXT")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS thread_access (
                    thread_id TEXT PRIMARY KEY,
                    root_thread_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    root_thread_id TEXT PRIMARY KEY,
                    owner_user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    title_pending_ai INTEGER NOT NULL DEFAULT 0,
                    is_archived INTEGER NOT NULL DEFAULT 0,
                    archived_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conversation_columns = {row['name'] for row in conn.execute('PRAGMA table_info(conversations)').fetchall()}
            if 'title_pending_ai' not in conversation_columns:
                conn.execute("ALTER TABLE conversations ADD COLUMN title_pending_ai INTEGER NOT NULL DEFAULT 0")
            if 'is_archived' not in conversation_columns:
                conn.execute("ALTER TABLE conversations ADD COLUMN is_archived INTEGER NOT NULL DEFAULT 0")
            if 'archived_at' not in conversation_columns:
                conn.execute("ALTER TABLE conversations ADD COLUMN archived_at TEXT")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_branches_root_thread ON branches(root_thread_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_branches_parent_thread ON branches(parent_thread_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_thread_access_root_thread ON thread_access(root_thread_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_conversations_owner_created ON conversations(owner_user_id, created_at DESC)"
            )
            conn.commit()

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> BranchRecord:
        return BranchRecord(
            branch_id=row['branch_id'],
            root_thread_id=row['root_thread_id'],
            parent_thread_id=row['parent_thread_id'],
            child_thread_id=row['child_thread_id'],
            return_thread_id=row['return_thread_id'],
            owner_user_id=row['owner_user_id'],
            branch_name=row['branch_name'],
            branch_role=row['branch_role'],
            branch_depth=row['branch_depth'],
            branch_status=row['branch_status'],
            is_archived=bool(row['is_archived']),
            archived_at=row['archived_at'],
            fork_checkpoint_id=row['fork_checkpoint_id'],
            fork_strategy=row['fork_strategy'],
            merge_proposal=json.loads(row['merge_proposal_json']) if row['merge_proposal_json'] else None,
            merge_decision=json.loads(row['merge_decision_json']) if row['merge_decision_json'] else None,
        )

    @staticmethod
    def _row_to_conversation(row: sqlite3.Row) -> ConversationRecord:
        return ConversationRecord(
            root_thread_id=row['root_thread_id'],
            owner_user_id=row['owner_user_id'],
            title=row['title'],
            title_pending_ai=bool(row['title_pending_ai']),
            is_archived=bool(row['is_archived']),
            archived_at=row['archived_at'],
            created_at=row['created_at'],
            updated_at=row['updated_at'],
        )

    @staticmethod
    def _default_conversation_title(root_thread_id: str) -> str:
        return 'Main' if root_thread_id.endswith('-main') else root_thread_id

    def _backfill_conversations(self, *, owner_user_id: str) -> None:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ta.root_thread_id
                FROM thread_access ta
                LEFT JOIN conversations c ON c.root_thread_id = ta.root_thread_id
                WHERE ta.owner_user_id = ?
                  AND ta.thread_id = ta.root_thread_id
                  AND c.root_thread_id IS NULL
                ORDER BY ta.created_at DESC, ta.root_thread_id DESC
                """,
                (owner_user_id,),
            ).fetchall()
            for row in rows:
                root_thread_id = str(row['root_thread_id'])
                conn.execute(
                    """
                    INSERT INTO conversations (root_thread_id, owner_user_id, title, title_pending_ai, is_archived, archived_at)
                    VALUES (?, ?, ?, ?, 0, NULL)
                    """,
                    (
                        root_thread_id,
                        owner_user_id,
                        self._default_conversation_title(root_thread_id),
                        1,
                    ),
                )
            conn.commit()

    def create(self, record: BranchRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO branches (
                    branch_id, root_thread_id, parent_thread_id, child_thread_id, return_thread_id,
                    owner_user_id, branch_name, branch_role, branch_depth, branch_status,
                    is_archived, archived_at, fork_checkpoint_id, fork_strategy,
                    merge_proposal_json, merge_decision_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.branch_id,
                    record.root_thread_id,
                    record.parent_thread_id,
                    record.child_thread_id,
                    record.return_thread_id,
                    record.owner_user_id,
                    record.branch_name,
                    record.branch_role.value,
                    record.branch_depth,
                    record.branch_status.value,
                    int(record.is_archived),
                    record.archived_at,
                    record.fork_checkpoint_id,
                    record.fork_strategy,
                    json.dumps(record.merge_proposal) if record.merge_proposal else None,
                    json.dumps(record.merge_decision) if record.merge_decision else None,
                ),
            )
            conn.commit()

    def get(self, branch_id: str) -> BranchRecord:
        with self._connect() as conn:
            row = conn.execute('SELECT * FROM branches WHERE branch_id = ?', (branch_id,)).fetchone()
        if row is None:
            raise KeyError(f'Unknown branch_id: {branch_id}')
        return self._row_to_record(row)

    def get_by_child_thread_id(self, child_thread_id: str) -> BranchRecord:
        with self._connect() as conn:
            row = conn.execute(
                'SELECT * FROM branches WHERE child_thread_id = ?', (child_thread_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f'Unknown child_thread_id: {child_thread_id}')
        return self._row_to_record(row)

    def list_by_root_thread_id(self, root_thread_id: str) -> list[BranchRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                'SELECT * FROM branches WHERE root_thread_id = ? ORDER BY branch_depth, branch_name, child_thread_id',
                (root_thread_id,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_by_parent_thread_id(self, parent_thread_id: str) -> list[BranchRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                'SELECT * FROM branches WHERE parent_thread_id = ? ORDER BY branch_name, child_thread_id',
                (parent_thread_id,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def save_merge_proposal(self, branch_id: str, proposal: MergeProposal) -> None:
        with self._connect() as conn:
            conn.execute(
                'UPDATE branches SET merge_proposal_json = ? WHERE branch_id = ?',
                (proposal.model_dump_json(), branch_id),
            )
            conn.commit()

    def save_merge_decision(self, branch_id: str, decision: MergeDecision) -> None:
        with self._connect() as conn:
            conn.execute(
                'UPDATE branches SET merge_decision_json = ? WHERE branch_id = ?',
                (decision.model_dump_json(), branch_id),
            )
            conn.commit()

    def update_status(self, branch_id: str, status: BranchStatus) -> None:
        with self._connect() as conn:
            conn.execute(
                'UPDATE branches SET branch_status = ? WHERE branch_id = ?',
                (status.value, branch_id),
            )
            conn.commit()

    def update_archive_state(self, branch_id: str, *, is_archived: bool) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE branches
                SET is_archived = ?, archived_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END
                WHERE branch_id = ?
                """,
                (int(is_archived), int(is_archived), branch_id),
            )
            conn.commit()

    def update_branch_name(self, branch_id: str, branch_name: str) -> None:
        with self._connect() as conn:
            conn.execute(
                'UPDATE branches SET branch_name = ? WHERE branch_id = ?',
                (branch_name, branch_id),
            )
            conn.commit()

    def update_branch_role(self, branch_id: str, branch_role: BranchRole) -> None:
        with self._connect() as conn:
            conn.execute(
                'UPDATE branches SET branch_role = ? WHERE branch_id = ?',
                (branch_role.value, branch_id),
            )
            conn.commit()

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
            existing = conn.execute(
                'SELECT owner_user_id FROM thread_access WHERE thread_id = ?', (thread_id,)
            ).fetchone()
            if existing is None:
                conn.execute(
                    'INSERT INTO thread_access (thread_id, root_thread_id, owner_user_id) VALUES (?, ?, ?)',
                    (thread_id, root_thread_id, owner_user_id),
                )
                conn.commit()
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
            if existing['owner_user_id'] != owner_user_id:
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
        with self._connect() as conn:
            row = conn.execute(
                'SELECT owner_user_id FROM thread_access WHERE thread_id = ?', (thread_id,)
            ).fetchone()
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
        if row['owner_user_id'] != owner_user_id:
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
            row = conn.execute(
                'SELECT owner_user_id FROM thread_access WHERE thread_id = ?', (thread_id,)
            ).fetchone()
        return None if row is None else str(row['owner_user_id'])

    def create_conversation(self, record: ConversationRecord) -> ConversationRecord:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO conversations (root_thread_id, owner_user_id, title, title_pending_ai, is_archived, archived_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    record.root_thread_id,
                    record.owner_user_id,
                    record.title,
                    int(record.title_pending_ai),
                    int(record.is_archived),
                    record.archived_at,
                ),
            )
            conn.commit()
        return self.get_conversation(record.root_thread_id)

    def get_conversation(self, root_thread_id: str) -> ConversationRecord:
        with self._connect() as conn:
            row = conn.execute(
                'SELECT * FROM conversations WHERE root_thread_id = ?',
                (root_thread_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f'Unknown root_thread_id: {root_thread_id}')
        return self._row_to_conversation(row)

    def list_conversations(self, *, owner_user_id: str) -> list[ConversationRecord]:
        self._backfill_conversations(owner_user_id=owner_user_id)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM conversations
                WHERE owner_user_id = ?
                ORDER BY is_archived ASC, created_at DESC, root_thread_id DESC
                """,
                (owner_user_id,),
            ).fetchall()
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
            row = conn.execute(
                'SELECT owner_user_id FROM conversations WHERE root_thread_id = ?',
                (root_thread_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f'Unknown root_thread_id: {root_thread_id}')
            if str(row['owner_user_id']) != owner_user_id:
                raise PermissionError(f'User {owner_user_id} cannot update conversation {root_thread_id}.')
            if title_pending_ai is None:
                conn.execute(
                    """
                    UPDATE conversations
                    SET title = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE root_thread_id = ?
                    """,
                    (title, root_thread_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE conversations
                    SET title = ?, title_pending_ai = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE root_thread_id = ?
                    """,
                    (title, int(title_pending_ai), root_thread_id),
                )
            conn.commit()
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
            row = conn.execute(
                'SELECT owner_user_id FROM conversations WHERE root_thread_id = ?',
                (root_thread_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f'Unknown root_thread_id: {root_thread_id}')
            if str(row['owner_user_id']) != owner_user_id:
                raise PermissionError(f'User {owner_user_id} cannot update conversation {root_thread_id}.')
            conn.execute(
                """
                UPDATE conversations
                SET is_archived = ?,
                    archived_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE root_thread_id = ?
                """,
                (int(is_archived), int(is_archived), root_thread_id),
            )
            conn.commit()
        return self.get_conversation(root_thread_id)
