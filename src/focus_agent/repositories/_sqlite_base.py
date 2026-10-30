from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from pathlib import Path


class SQLiteRepositoryBase:
    """Shared connection and lightweight-migration helpers for local SQLite repositories."""

    def __init__(self, db_path: str):
        self.db_path = str(Path(db_path).expanduser())
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._setup()

    def _setup(self) -> None:
        raise NotImplementedError

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _add_columns_if_missing(
        conn: sqlite3.Connection,
        table_name: str,
        columns: Mapping[str, str],
    ) -> None:
        existing = {
            row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        for column_name, definition in columns.items():
            if column_name not in existing:
                conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


__all__ = ["SQLiteRepositoryBase"]
