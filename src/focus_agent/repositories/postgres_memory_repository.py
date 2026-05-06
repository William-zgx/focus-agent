from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from focus_agent.memory.models import (
    MemoryAuditEvent,
    MemoryCandidate,
    MemoryRecord,
    MemorySearchHit,
    MemoryStatus,
)

from .memory_repository import MemoryListQuery, MemoryRepository
from .postgres_schema import ensure_app_postgres_schema_on_connection


class PostgresMemoryRepository(MemoryRepository):
    def __init__(self, database_uri: str):
        self.database_uri = database_uri

    def setup(self) -> None:
        with psycopg.connect(self.database_uri) as conn:
            ensure_app_postgres_schema_on_connection(conn)

    def _connect(self):
        return psycopg.connect(self.database_uri, row_factory=dict_row)

    def upsert_record(self, record: MemoryRecord) -> str:
        payload = record.model_dump(mode="json")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO focus_memories (
                        memory_id, namespace, kind, scope, visibility, status,
                        user_id, root_thread_id, source_thread_id, source_branch_id,
                        semantic_key, fingerprint, confidence, importance,
                        summary, content, promoted_to_main,
                        created_at, updated_at, deleted_at, data_json
                    ) VALUES (
                        %(memory_id)s, %(namespace)s, %(kind)s, %(scope)s, %(visibility)s, %(status)s,
                        %(user_id)s, %(root_thread_id)s, %(source_thread_id)s, %(source_branch_id)s,
                        %(semantic_key)s, %(fingerprint)s, %(confidence)s, %(importance)s,
                        %(summary)s, %(content)s, %(promoted_to_main)s,
                        %(created_at)s, %(updated_at)s, %(deleted_at)s, %(data_json)s
                    )
                    ON CONFLICT (memory_id) DO UPDATE SET
                        namespace = EXCLUDED.namespace,
                        kind = EXCLUDED.kind,
                        scope = EXCLUDED.scope,
                        visibility = EXCLUDED.visibility,
                        status = EXCLUDED.status,
                        user_id = EXCLUDED.user_id,
                        root_thread_id = EXCLUDED.root_thread_id,
                        source_thread_id = EXCLUDED.source_thread_id,
                        source_branch_id = EXCLUDED.source_branch_id,
                        semantic_key = EXCLUDED.semantic_key,
                        fingerprint = EXCLUDED.fingerprint,
                        confidence = EXCLUDED.confidence,
                        importance = EXCLUDED.importance,
                        summary = EXCLUDED.summary,
                        content = EXCLUDED.content,
                        promoted_to_main = EXCLUDED.promoted_to_main,
                        updated_at = EXCLUDED.updated_at,
                        deleted_at = EXCLUDED.deleted_at,
                        data_json = EXCLUDED.data_json
                    """,
                    _record_params(record, payload=payload),
                )
        return record.memory_id

    def find_existing(
        self,
        *,
        namespace: tuple[str, ...],
        fingerprint: str,
        semantic_key: str,
        kind: str | None = None,
        scope: str | None = None,
    ) -> MemoryRecord | None:
        clauses = [
            "namespace = %(namespace)s",
            "status != 'forgotten'",
            "deleted_at IS NULL",
            "(fingerprint = %(fingerprint)s OR semantic_key = %(semantic_key)s)",
        ]
        params: dict[str, Any] = {
            "namespace": list(namespace),
            "fingerprint": fingerprint,
            "semantic_key": semantic_key,
        }
        if kind:
            clauses.append("kind = %(kind)s")
            params["kind"] = kind
        if scope:
            clauses.append("scope = %(scope)s")
            params["scope"] = scope
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT data_json
                    FROM focus_memories
                    WHERE {' AND '.join(clauses)}
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    params,
                )
                row = cur.fetchone()
        if row is None:
            return None
        return _record_from_payload(row["data_json"])

    def search(
        self,
        *,
        namespace: tuple[str, ...],
        query: str,
        limit: int,
    ) -> list[MemorySearchHit]:
        normalized_query = " ".join((query or "").split())
        like_query = f"%{normalized_query}%" if normalized_query else "%"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT data_json,
                           CASE
                             WHEN %(query)s = '' THEN 0.0
                             ELSE ts_rank_cd(
                               to_tsvector('simple', coalesce(summary, '') || ' ' || coalesce(content, '')),
                               plainto_tsquery('simple', %(query)s)
                             )
                           END AS text_score
                    FROM focus_memories
                    WHERE namespace = %(namespace)s
                      AND status = 'active'
                      AND deleted_at IS NULL
                      AND (
                        %(query)s = ''
                        OR to_tsvector('simple', coalesce(summary, '') || ' ' || coalesce(content, ''))
                           @@ plainto_tsquery('simple', %(query)s)
                        OR summary ILIKE %(like_query)s
                        OR content ILIKE %(like_query)s
                      )
                    ORDER BY text_score DESC, importance DESC, updated_at DESC
                    LIMIT %(limit)s
                    """,
                    {
                        "namespace": list(namespace),
                        "query": normalized_query,
                        "like_query": like_query,
                        "limit": max(1, int(limit)),
                    },
                )
                rows = cur.fetchall()
        hits: list[MemorySearchHit] = []
        for row in rows:
            record = _record_from_payload(row["data_json"])
            score = float(row.get("text_score") or 0.0)
            hits.append(MemorySearchHit(record=record, score=score, namespace=record.namespace))
        return hits

    def list_records(self, query: MemoryListQuery) -> list[MemoryRecord]:
        clauses = [] if query.status == MemoryStatus.FORGOTTEN.value else ["deleted_at IS NULL"]
        params: dict[str, Any] = {"limit": max(1, int(query.limit)), "offset": max(0, int(query.offset))}
        for field in (
            "kind",
            "scope",
            "visibility",
            "status",
            "user_id",
            "root_thread_id",
            "source_thread_id",
            "source_branch_id",
        ):
            value = getattr(query, field)
            if value is not None:
                clauses.append(f"{field} = %({field})s")
                params[field] = value
        if query.namespace is not None:
            clauses.append("namespace = %(namespace)s")
            params["namespace"] = list(query.namespace)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT data_json
                    FROM focus_memories
                    WHERE {' AND '.join(clauses)}
                    ORDER BY updated_at DESC, memory_id DESC
                    LIMIT %(limit)s OFFSET %(offset)s
                    """,
                    params,
                )
                rows = cur.fetchall()
        return [_record_from_payload(row["data_json"]) for row in rows]

    def get_record(self, memory_id: str) -> MemoryRecord | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT data_json FROM focus_memories WHERE memory_id = %s", (memory_id,))
                row = cur.fetchone()
        if row is None:
            return None
        return _record_from_payload(row["data_json"])

    def forget_record(
        self,
        *,
        memory_id: str,
        namespace: tuple[str, ...] | None = None,
        actor: str | None = None,
        reason: str | None = None,
    ) -> str | None:
        existing = self.get_record(memory_id)
        if existing is None:
            return None
        if namespace is not None and existing.namespace != namespace:
            return None
        now = datetime.now(timezone.utc)
        updated = existing.model_copy(
            update={
                "status": MemoryStatus.FORGOTTEN,
                "content": "",
                "summary": "[forgotten]",
                "deleted_at": now,
                "updated_at": now,
            }
        )
        self.upsert_record(updated)
        tombstone_id = str(uuid4())
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO focus_memory_tombstones (
                        tombstone_id, memory_id, namespace, semantic_key, fingerprint,
                        actor, reason, created_at, data_json
                    ) VALUES (
                        %(tombstone_id)s, %(memory_id)s, %(namespace)s, %(semantic_key)s, %(fingerprint)s,
                        %(actor)s, %(reason)s, %(created_at)s, %(data_json)s
                    )
                    ON CONFLICT (memory_id) DO UPDATE SET
                        namespace = EXCLUDED.namespace,
                        semantic_key = EXCLUDED.semantic_key,
                        fingerprint = EXCLUDED.fingerprint,
                        actor = EXCLUDED.actor,
                        reason = EXCLUDED.reason,
                        created_at = EXCLUDED.created_at,
                        data_json = EXCLUDED.data_json
                    RETURNING tombstone_id
                    """,
                    {
                        "tombstone_id": tombstone_id,
                        "memory_id": memory_id,
                        "namespace": list(existing.namespace),
                        "semantic_key": existing.semantic_key,
                        "fingerprint": existing.fingerprint,
                        "actor": actor,
                        "reason": reason,
                        "created_at": now,
                        "data_json": Jsonb(
                            {
                                "memory_id": memory_id,
                                "namespace": list(existing.namespace),
                                "semantic_key": existing.semantic_key,
                                "fingerprint": existing.fingerprint,
                                "actor": actor,
                                "reason": reason,
                                "created_at": now.isoformat(),
                            }
                        ),
                    },
                )
                row = cur.fetchone()
        return str(row["tombstone_id"]) if row else tombstone_id

    def append_audit_event(self, event: MemoryAuditEvent) -> str:
        payload = event.model_dump(mode="json")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO focus_memory_audit_events (
                        event_id, action, decision, memory_id, candidate_id, actor,
                        reason, namespace, user_id, root_thread_id, source_thread_id,
                        source_branch_id, request_id, created_at, data_json
                    ) VALUES (
                        %(event_id)s, %(action)s, %(decision)s, %(memory_id)s, %(candidate_id)s, %(actor)s,
                        %(reason)s, %(namespace)s, %(user_id)s, %(root_thread_id)s, %(source_thread_id)s,
                        %(source_branch_id)s, %(request_id)s, %(created_at)s, %(data_json)s
                    )
                    ON CONFLICT (event_id) DO NOTHING
                    """,
                    {
                        **payload,
                        "decision": str(payload.get("decision") or ""),
                        "namespace": list(event.namespace),
                        "data_json": Jsonb(payload),
                    },
                )
        return event.event_id

    def list_audit_events(
        self,
        *,
        memory_id: str | None = None,
        user_id: str | None = None,
        root_thread_id: str | None = None,
        source_thread_id: str | None = None,
        source_branch_id: str | None = None,
        limit: int = 50,
    ) -> list[MemoryAuditEvent]:
        params: dict[str, Any] = {"limit": max(1, int(limit))}
        clauses: list[str] = []
        for field, value in (
            ("memory_id", memory_id),
            ("user_id", user_id),
            ("root_thread_id", root_thread_id),
            ("source_thread_id", source_thread_id),
            ("source_branch_id", source_branch_id),
        ):
            if value is not None:
                clauses.append(f"{field} = %({field})s")
                params[field] = value
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT data_json
                    FROM focus_memory_audit_events
                    {where}
                    ORDER BY created_at DESC, event_id DESC
                    LIMIT %(limit)s
                    """,
                    params,
                )
                rows = cur.fetchall()
        return [MemoryAuditEvent.model_validate(_decode_json(row["data_json"])) for row in rows]

    def upsert_candidate(self, candidate: MemoryCandidate) -> str:
        payload = candidate.model_dump(mode="json")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO focus_memory_candidates (
                        candidate_id, status, agent_id, task_id, branch_id,
                        root_thread_id, user_id, evidence_refs, created_at, updated_at, data_json
                    ) VALUES (
                        %(candidate_id)s, %(status)s, %(agent_id)s, %(task_id)s, %(branch_id)s,
                        %(root_thread_id)s, %(user_id)s, %(evidence_refs)s, %(created_at)s,
                        %(updated_at)s, %(data_json)s
                    )
                    ON CONFLICT (candidate_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        agent_id = EXCLUDED.agent_id,
                        task_id = EXCLUDED.task_id,
                        branch_id = EXCLUDED.branch_id,
                        root_thread_id = EXCLUDED.root_thread_id,
                        user_id = EXCLUDED.user_id,
                        evidence_refs = EXCLUDED.evidence_refs,
                        updated_at = EXCLUDED.updated_at,
                        data_json = EXCLUDED.data_json
                    """,
                    {
                        **payload,
                        "evidence_refs": list(candidate.evidence_refs),
                        "data_json": Jsonb(payload),
                    },
                )
        return candidate.candidate_id

    def list_candidates(
        self,
        *,
        status: str | None = None,
        root_thread_id: str | None = None,
        user_id: str | None = None,
        branch_id: str | None = None,
        limit: int = 50,
    ) -> list[MemoryCandidate]:
        clauses: list[str] = []
        params: dict[str, Any] = {"limit": max(1, int(limit))}
        if status:
            clauses.append("status = %(status)s")
            params["status"] = status
        if root_thread_id:
            clauses.append("root_thread_id = %(root_thread_id)s")
            params["root_thread_id"] = root_thread_id
        if user_id:
            clauses.append("user_id = %(user_id)s")
            params["user_id"] = user_id
        if branch_id:
            clauses.append("branch_id = %(branch_id)s")
            params["branch_id"] = branch_id
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT data_json
                    FROM focus_memory_candidates
                    {where}
                    ORDER BY updated_at DESC, candidate_id DESC
                    LIMIT %(limit)s
                    """,
                    params,
                )
                rows = cur.fetchall()
        return [MemoryCandidate.model_validate(_decode_json(row["data_json"])) for row in rows]

    def update_candidate_status(
        self,
        *,
        candidate_id: str,
        status: str,
        reason: str | None = None,
    ) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT data_json
                    FROM focus_memory_candidates
                    WHERE candidate_id = %s
                    """,
                    (candidate_id,),
                )
                row = cur.fetchone()
        if row is None:
            return
        candidate = MemoryCandidate.model_validate(_decode_json(row["data_json"]))
        now = datetime.now(timezone.utc)
        updated = candidate.model_copy(update={"status": status, "reason": reason, "updated_at": now})
        self.upsert_candidate(updated)


def _record_params(record: MemoryRecord, *, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "memory_id": record.memory_id,
        "namespace": list(record.namespace),
        "kind": record.kind.value,
        "scope": record.scope.value,
        "visibility": record.visibility.value,
        "status": record.status.value,
        "user_id": record.user_id,
        "root_thread_id": record.root_thread_id,
        "source_thread_id": record.source_thread_id,
        "source_branch_id": record.source_branch_id,
        "semantic_key": record.semantic_key,
        "fingerprint": record.fingerprint,
        "confidence": record.confidence,
        "importance": record.importance,
        "summary": record.summary,
        "content": record.content,
        "promoted_to_main": record.promoted_to_main,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "deleted_at": record.deleted_at,
        "data_json": Jsonb(payload),
    }


def _record_from_payload(payload: object) -> MemoryRecord:
    data = _decode_json(payload)
    return MemoryRecord.model_validate(data)


def _decode_json(value: object) -> dict[str, Any]:
    if isinstance(value, str):
        return json.loads(value)
    if isinstance(value, dict):
        return value
    return dict(value)  # type: ignore[arg-type]


__all__ = ["PostgresMemoryRepository"]
