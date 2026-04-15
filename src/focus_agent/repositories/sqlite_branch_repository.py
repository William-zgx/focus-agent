from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..core.branching import BranchRecord, BranchStatus, MergeDecision, MergeProposal
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
                "CREATE INDEX IF NOT EXISTS idx_branches_root_thread ON branches(root_thread_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_branches_parent_thread ON branches(parent_thread_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_thread_access_root_thread ON thread_access(root_thread_id)"
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

    def ensure_thread_owner(self, *, thread_id: str, root_thread_id: str, owner_user_id: str) -> None:
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
                return
            if existing['owner_user_id'] != owner_user_id:
                raise PermissionError(f'User {owner_user_id} cannot access thread {thread_id}.')

    def assert_thread_owner(self, *, thread_id: str, owner_user_id: str) -> None:
        with self._connect() as conn:
            row = conn.execute(
                'SELECT owner_user_id FROM thread_access WHERE thread_id = ?', (thread_id,)
            ).fetchone()
        if row is None:
            raise PermissionError(f'Thread {thread_id} is not registered for access yet.')
        if row['owner_user_id'] != owner_user_id:
            raise PermissionError(f'User {owner_user_id} cannot access thread {thread_id}.')

    def get_thread_owner(self, *, thread_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                'SELECT owner_user_id FROM thread_access WHERE thread_id = ?', (thread_id,)
            ).fetchone()
        return None if row is None else str(row['owner_user_id'])
