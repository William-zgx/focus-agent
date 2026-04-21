from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import uuid

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .postgres_schema import ensure_app_postgres_schema_on_connection


@dataclass(frozen=True, slots=True)
class ArtifactMetadataRecord:
    artifact_id: str
    thread_id: str | None
    path: str
    title: str
    size_bytes: int
    created_at: datetime
    updated_at: datetime


class ArtifactMetadataRepository:
    def __init__(self, database_uri: str):
        self.database_uri = database_uri

    def setup(self) -> None:
        with psycopg.connect(self.database_uri) as conn:
            ensure_app_postgres_schema_on_connection(conn)

    def upsert_from_file(
        self,
        *,
        thread_id: str | None,
        artifact_id: str,
        path: str | Path,
        title: str,
    ) -> ArtifactMetadataRecord:
        file_path = Path(path).expanduser()
        stat = file_path.stat()
        updated_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
        created_at = datetime.now(timezone.utc)
        relative_path = str(artifact_id)
        internal_artifact_id = str(uuid.uuid5(uuid.NAMESPACE_URL, relative_path))
        path_text = str(file_path)

        with psycopg.connect(self.database_uri) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    INSERT INTO focus_artifacts (
                        artifact_id,
                        title,
                        kind,
                        uri,
                        relative_path,
                        root_thread_id,
                        source_thread_id,
                        source_branch_id,
                        summary,
                        size_bytes,
                        checksum,
                        created_at,
                        updated_at,
                        metadata
                    )
                    VALUES (
                        %(artifact_id)s,
                        %(title)s,
                        'text',
                        %(uri)s,
                        %(relative_path)s,
                        %(root_thread_id)s,
                        %(source_thread_id)s,
                        NULL,
                        NULL,
                        %(size_bytes)s,
                        NULL,
                        %(created_at)s,
                        %(updated_at)s,
                        %(metadata)s
                    )
                    ON CONFLICT (relative_path) DO UPDATE
                    SET
                        title = EXCLUDED.title,
                        uri = EXCLUDED.uri,
                        root_thread_id = EXCLUDED.root_thread_id,
                        source_thread_id = EXCLUDED.source_thread_id,
                        size_bytes = EXCLUDED.size_bytes,
                        updated_at = EXCLUDED.updated_at,
                        metadata = EXCLUDED.metadata
                    RETURNING
                        relative_path,
                        source_thread_id,
                        uri,
                        title,
                        size_bytes,
                        created_at,
                        updated_at
                    """,
                    {
                        "artifact_id": internal_artifact_id,
                        "title": title,
                        "uri": path_text,
                        "relative_path": relative_path,
                        "root_thread_id": thread_id,
                        "source_thread_id": thread_id,
                        "size_bytes": stat.st_size,
                        "created_at": created_at,
                        "updated_at": updated_at,
                        "metadata": Jsonb({"path": path_text}),
                    },
                )
                row = cur.fetchone()
        if row is None:
            raise RuntimeError(f"Failed to upsert artifact metadata for {artifact_id}.")
        return self._row_to_record(row)

    def list_by_thread(self, thread_id: str, *, limit: int | None = None) -> list[ArtifactMetadataRecord]:
        query = """
            SELECT
                relative_path,
                source_thread_id,
                uri,
                title,
                size_bytes,
                created_at,
                updated_at
            FROM focus_artifacts
            WHERE source_thread_id = %(thread_id)s OR root_thread_id = %(thread_id)s
            ORDER BY updated_at DESC, relative_path
        """
        params: dict[str, object] = {"thread_id": thread_id}
        if limit is not None:
            query += " LIMIT %(limit)s"
            params["limit"] = limit

        with psycopg.connect(self.database_uri) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
        return [self._row_to_record(row) for row in rows]

    def get_by_artifact_id(self, artifact_id: str) -> ArtifactMetadataRecord | None:
        with psycopg.connect(self.database_uri) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT
                        relative_path,
                        source_thread_id,
                        uri,
                        title,
                        size_bytes,
                        created_at,
                        updated_at
                    FROM focus_artifacts
                    WHERE relative_path = %(artifact_id)s
                    """,
                    {"artifact_id": artifact_id},
                )
                row = cur.fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    @staticmethod
    def _row_to_record(row: dict[str, object]) -> ArtifactMetadataRecord:
        return ArtifactMetadataRecord(
            artifact_id=str(row["relative_path"]),
            thread_id=None if row["source_thread_id"] is None else str(row["source_thread_id"]),
            path=str(row["uri"]),
            title=str(row["title"]),
            size_bytes=int(row["size_bytes"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
