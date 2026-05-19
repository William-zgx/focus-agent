from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from focus_agent.core.governance import (
    BranchDecisionEvent,
    ContextMemoryEvidence,
    FeedbackEvent,
    SkillPreference,
    SkillSelectionEvent,
)

_CONTEXT_MEMORY_EVIDENCE_COLUMNS = """
    evidence_id, user_id, thread_id, turn_id, source_kind,
    selected_memories, excluded_memories, compaction_summary,
    drift_report, artifact_refs, token_counting, risk_flags,
    data_json, created_at
"""

_SKILL_SELECTION_EVENT_COLUMNS = """
    selection_id, user_id, message_hash, selection_source,
    explicit_hints, activated_skill_ids, semantic_candidates,
    confidence, feedback, user_override, data_json, created_at, updated_at
"""

_SKILL_PREFERENCE_COLUMNS = """
    preference_id, user_id, skill_id, state, data_json, created_at, updated_at
"""

_BRANCH_DECISION_EVENT_COLUMNS = """
    decision_id, user_id, root_thread_id, source_thread_id,
    branch_id, action, status, mode, score, threshold, signals,
    rationale, request_id, trace_id, idempotency_key,
    promoted_action_id, dismiss_reason, error, metadata,
    data_json, created_at, updated_at, executed_at
"""


class PostgresGovernanceRepository:
    def __init__(self, database_uri: str):
        self.database_uri = database_uri

    def _connect(self):
        return psycopg.connect(self.database_uri, row_factory=dict_row)

    @staticmethod
    def _decode_payload(value: object) -> dict[str, Any]:
        if isinstance(value, str):
            return json.loads(value)
        if isinstance(value, dict):
            return value
        return dict(value)  # type: ignore[arg-type]

    @classmethod
    def _context_evidence_from_row(cls, row: dict[str, object]) -> ContextMemoryEvidence:
        payload = cls._decode_payload(row["data_json"])
        payload["evidence_id"] = row.get("evidence_id")
        payload["user_id"] = row.get("user_id")
        payload["thread_id"] = row.get("thread_id")
        payload["turn_id"] = row.get("turn_id")
        payload["source_kind"] = row.get("source_kind") or "context_explain"
        payload.setdefault(
            "selected_memories", cls._decode_jsonish(row.get("selected_memories"), [])
        )
        payload.setdefault(
            "excluded_memories", cls._decode_jsonish(row.get("excluded_memories"), [])
        )
        payload.setdefault(
            "compaction_summary", cls._decode_jsonish(row.get("compaction_summary"), {})
        )
        payload.setdefault("drift_report", cls._decode_jsonish(row.get("drift_report"), {}))
        payload.setdefault("artifact_refs", cls._decode_jsonish(row.get("artifact_refs"), []))
        payload.setdefault("token_counting", cls._decode_jsonish(row.get("token_counting"), {}))
        payload.setdefault("risk_flags", list(row.get("risk_flags") or []))
        payload["created_at"] = cls._iso_datetime(row.get("created_at"))
        return ContextMemoryEvidence.model_validate(payload)

    @classmethod
    def _skill_event_from_row(cls, row: dict[str, object]) -> SkillSelectionEvent:
        payload = cls._decode_payload(row["data_json"])
        payload["selection_id"] = row.get("selection_id")
        payload["user_id"] = row.get("user_id")
        payload["message_hash"] = row.get("message_hash")
        payload["selection_source"] = row.get("selection_source") or "none"
        payload["explicit_hints"] = list(row.get("explicit_hints") or [])
        payload["activated_skill_ids"] = list(row.get("activated_skill_ids") or [])
        payload["semantic_candidates"] = cls._decode_jsonish(row.get("semantic_candidates"), [])
        payload["confidence"] = row.get("confidence") or 0.0
        payload["feedback"] = row.get("feedback")
        payload["user_override"] = cls._decode_jsonish(row.get("user_override"), {})
        payload["created_at"] = cls._iso_datetime(row.get("created_at"))
        payload["updated_at"] = cls._iso_datetime(row.get("updated_at"))
        return SkillSelectionEvent.model_validate(payload)

    @classmethod
    def _skill_preference_from_row(cls, row: dict[str, object]) -> SkillPreference:
        payload = cls._decode_payload(row["data_json"])
        payload["preference_id"] = row.get("preference_id")
        payload["user_id"] = row.get("user_id")
        payload["skill_id"] = row.get("skill_id")
        payload["state"] = row.get("state") or "default"
        payload["created_at"] = cls._iso_datetime(row.get("created_at"))
        payload["updated_at"] = cls._iso_datetime(row.get("updated_at"))
        return SkillPreference.model_validate(payload)

    @classmethod
    def _branch_decision_from_row(cls, row: dict[str, object]) -> BranchDecisionEvent:
        payload = cls._decode_payload(row["data_json"])
        payload["decision_id"] = row.get("decision_id")
        payload["user_id"] = row.get("user_id")
        payload["root_thread_id"] = row.get("root_thread_id")
        payload["source_thread_id"] = row.get("source_thread_id")
        payload["branch_id"] = row.get("branch_id")
        payload["action"] = row.get("action")
        payload["status"] = row.get("status")
        payload["mode"] = row.get("mode")
        payload["score"] = row.get("score") or 0.0
        payload["threshold"] = row.get("threshold") or 0.0
        payload["signals"] = cls._decode_jsonish(row.get("signals"), payload.get("signals", []))
        payload["rationale"] = row.get("rationale") or ""
        payload["request_id"] = row.get("request_id")
        payload["trace_id"] = row.get("trace_id")
        payload["idempotency_key"] = row.get("idempotency_key")
        payload["promoted_action_id"] = row.get("promoted_action_id")
        payload["dismiss_reason"] = row.get("dismiss_reason")
        payload["error"] = row.get("error")
        payload["metadata"] = cls._decode_jsonish(row.get("metadata"), payload.get("metadata", {}))
        payload["created_at"] = cls._iso_datetime(row.get("created_at"))
        payload["updated_at"] = cls._iso_datetime(row.get("updated_at"))
        payload["executed_at"] = cls._iso_datetime(row.get("executed_at"))
        return BranchDecisionEvent.model_validate(payload)

    @staticmethod
    def _decode_jsonish(value: object, default: object) -> object:
        if value is None:
            return default
        if isinstance(value, str):
            return json.loads(value)
        return value

    @staticmethod
    def _iso_datetime(value: object) -> str | None:
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return str(value.isoformat())
        return str(value)

    def save_context_evidence(self, evidence: ContextMemoryEvidence) -> str:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO focus_context_memory_evidence (
                        evidence_id, user_id, thread_id, turn_id, source_kind,
                        selected_memories, excluded_memories, compaction_summary,
                        drift_report, artifact_refs, token_counting, risk_flags,
                        data_json, created_at
                    ) VALUES (
                        %(evidence_id)s, %(user_id)s, %(thread_id)s, %(turn_id)s,
                        %(source_kind)s, %(selected_memories)s, %(excluded_memories)s,
                        %(compaction_summary)s, %(drift_report)s, %(artifact_refs)s,
                        %(token_counting)s, %(risk_flags)s, %(data_json)s, %(created_at)s
                    )
                    ON CONFLICT (evidence_id) DO UPDATE SET
                        user_id = EXCLUDED.user_id,
                        thread_id = EXCLUDED.thread_id,
                        turn_id = EXCLUDED.turn_id,
                        source_kind = EXCLUDED.source_kind,
                        selected_memories = EXCLUDED.selected_memories,
                        excluded_memories = EXCLUDED.excluded_memories,
                        compaction_summary = EXCLUDED.compaction_summary,
                        drift_report = EXCLUDED.drift_report,
                        artifact_refs = EXCLUDED.artifact_refs,
                        token_counting = EXCLUDED.token_counting,
                        risk_flags = EXCLUDED.risk_flags,
                        data_json = EXCLUDED.data_json
                    """,
                    {
                        "evidence_id": evidence.evidence_id,
                        "user_id": evidence.user_id,
                        "thread_id": evidence.thread_id,
                        "turn_id": evidence.turn_id,
                        "source_kind": evidence.source_kind,
                        "selected_memories": Jsonb(evidence.selected_memories),
                        "excluded_memories": Jsonb(evidence.excluded_memories),
                        "compaction_summary": Jsonb(evidence.compaction_summary),
                        "drift_report": Jsonb(evidence.drift_report),
                        "artifact_refs": Jsonb(evidence.artifact_refs),
                        "token_counting": Jsonb(evidence.token_counting),
                        "risk_flags": evidence.risk_flags,
                        "data_json": Jsonb(evidence.model_dump(mode="json")),
                        "created_at": evidence.created_at,
                    },
                )
        return evidence.evidence_id

    def list_context_evidence(
        self,
        *,
        thread_id: str | None = None,
        turn_id: str | None = None,
        memory_id: str | None = None,
        user_id: str | None = None,
        limit: int = 50,
    ) -> list[ContextMemoryEvidence]:
        clauses: list[str] = []
        params: dict[str, object] = {"limit": max(0, limit)}
        if thread_id is not None:
            clauses.append("thread_id = %(thread_id)s")
            params["thread_id"] = thread_id
        if turn_id is not None:
            clauses.append("turn_id = %(turn_id)s")
            params["turn_id"] = turn_id
        if user_id is not None:
            clauses.append("(user_id IS NULL OR user_id = %(user_id)s)")
            params["user_id"] = user_id
        if memory_id is not None:
            clauses.append(
                """
                (
                    selected_memories @> %(memory_probe)s
                    OR excluded_memories @> %(memory_probe)s
                    OR selected_memories @> %(id_probe)s
                    OR excluded_memories @> %(id_probe)s
                )
                """
            )
            params["memory_probe"] = Jsonb([{"memory_id": memory_id}])
            params["id_probe"] = Jsonb([{"id": memory_id}])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT {_CONTEXT_MEMORY_EVIDENCE_COLUMNS}
                    FROM focus_context_memory_evidence
                    {where}
                    ORDER BY created_at DESC, evidence_id DESC
                    LIMIT %(limit)s
                    """,
                    params,
                )
                rows = cur.fetchall()
        return [self._context_evidence_from_row(row) for row in rows]

    def save_skill_selection_event(self, event: SkillSelectionEvent) -> str:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO focus_skill_selection_events (
                        selection_id, user_id, message_hash, selection_source,
                        explicit_hints, activated_skill_ids, semantic_candidates,
                        confidence, feedback, user_override, data_json, created_at, updated_at
                    ) VALUES (
                        %(selection_id)s, %(user_id)s, %(message_hash)s, %(selection_source)s,
                        %(explicit_hints)s, %(activated_skill_ids)s, %(semantic_candidates)s,
                        %(confidence)s, %(feedback)s, %(user_override)s, %(data_json)s,
                        %(created_at)s, %(updated_at)s
                    )
                    ON CONFLICT (selection_id) DO UPDATE SET
                        user_id = EXCLUDED.user_id,
                        message_hash = EXCLUDED.message_hash,
                        selection_source = EXCLUDED.selection_source,
                        explicit_hints = EXCLUDED.explicit_hints,
                        activated_skill_ids = EXCLUDED.activated_skill_ids,
                        semantic_candidates = EXCLUDED.semantic_candidates,
                        confidence = EXCLUDED.confidence,
                        feedback = EXCLUDED.feedback,
                        user_override = EXCLUDED.user_override,
                        data_json = EXCLUDED.data_json,
                        updated_at = EXCLUDED.updated_at
                    """,
                    {
                        "selection_id": event.selection_id,
                        "user_id": event.user_id,
                        "message_hash": event.message_hash,
                        "selection_source": event.selection_source,
                        "explicit_hints": event.explicit_hints,
                        "activated_skill_ids": event.activated_skill_ids,
                        "semantic_candidates": Jsonb(event.semantic_candidates),
                        "confidence": event.confidence,
                        "feedback": event.feedback,
                        "user_override": Jsonb(event.user_override),
                        "data_json": Jsonb(event.model_dump(mode="json")),
                        "created_at": event.created_at,
                        "updated_at": event.updated_at,
                    },
                )
        return event.selection_id

    def get_skill_selection_event(self, selection_id: str) -> SkillSelectionEvent | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT {_SKILL_SELECTION_EVENT_COLUMNS}
                    FROM focus_skill_selection_events
                    WHERE selection_id = %s
                    """,
                    (selection_id,),
                )
                row = cur.fetchone()
        return None if row is None else self._skill_event_from_row(row)

    def list_skill_selection_events(
        self,
        *,
        user_id: str | None = None,
        skill_id: str | None = None,
        limit: int = 50,
    ) -> list[SkillSelectionEvent]:
        clauses: list[str] = []
        params: dict[str, object] = {"limit": max(0, limit)}
        if user_id is not None:
            clauses.append("(user_id IS NULL OR user_id = %(user_id)s)")
            params["user_id"] = user_id
        if skill_id is not None:
            clauses.append("%(skill_id)s = ANY(activated_skill_ids)")
            params["skill_id"] = skill_id
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT {_SKILL_SELECTION_EVENT_COLUMNS}
                    FROM focus_skill_selection_events
                    {where}
                    ORDER BY created_at DESC, selection_id DESC
                    LIMIT %(limit)s
                    """,
                    params,
                )
                rows = cur.fetchall()
        return [self._skill_event_from_row(row) for row in rows]

    def update_skill_selection_feedback(
        self,
        *,
        selection_id: str,
        feedback: str,
        reason: str | None = None,
        user_override: dict[str, object] | None = None,
    ) -> SkillSelectionEvent | None:
        event = self.get_skill_selection_event(selection_id)
        if event is None:
            return None
        updated = event.model_copy(
            update={
                "feedback": feedback,
                "feedback_reason": reason,
                "user_override": dict(user_override or event.user_override),
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )
        self.save_skill_selection_event(updated)
        return self.get_skill_selection_event(selection_id)

    def save_skill_preference(self, preference: SkillPreference) -> SkillPreference:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO focus_skill_preferences (
                        preference_id, user_id, skill_id, state, data_json, created_at, updated_at
                    ) VALUES (
                        %(preference_id)s, %(user_id)s, %(skill_id)s, %(state)s,
                        %(data_json)s, %(created_at)s, %(updated_at)s
                    )
                    ON CONFLICT (user_id, skill_id) DO UPDATE SET
                        state = EXCLUDED.state,
                        data_json = EXCLUDED.data_json,
                        updated_at = EXCLUDED.updated_at
                    RETURNING *
                    """,
                    {
                        "preference_id": preference.preference_id,
                        "user_id": preference.user_id,
                        "skill_id": preference.skill_id,
                        "state": preference.state,
                        "data_json": Jsonb(preference.model_dump(mode="json")),
                        "created_at": preference.created_at,
                        "updated_at": preference.updated_at,
                    },
                )
                row = cur.fetchone()
        return self._skill_preference_from_row(row)

    def get_skill_preference(self, *, user_id: str, skill_id: str) -> SkillPreference | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT {_SKILL_PREFERENCE_COLUMNS}
                    FROM focus_skill_preferences
                    WHERE user_id = %s AND skill_id = %s
                    """,
                    (user_id, skill_id),
                )
                row = cur.fetchone()
        return None if row is None else self._skill_preference_from_row(row)

    def list_skill_preferences(self, *, user_id: str) -> list[SkillPreference]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT {_SKILL_PREFERENCE_COLUMNS}
                    FROM focus_skill_preferences
                    WHERE user_id = %s
                    ORDER BY updated_at DESC, skill_id
                    """,
                    (user_id,),
                )
                rows = cur.fetchall()
        return [self._skill_preference_from_row(row) for row in rows]

    def save_feedback_event(self, event: FeedbackEvent) -> str:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO focus_feedback_events (
                        event_id, user_id, source_kind, source_id, sentiment,
                        category, data_json, created_at
                    ) VALUES (
                        %(event_id)s, %(user_id)s, %(source_kind)s, %(source_id)s,
                        %(sentiment)s, %(category)s, %(data_json)s, %(created_at)s
                    )
                    ON CONFLICT (event_id) DO UPDATE SET
                        user_id = EXCLUDED.user_id,
                        source_kind = EXCLUDED.source_kind,
                        source_id = EXCLUDED.source_id,
                        sentiment = EXCLUDED.sentiment,
                        category = EXCLUDED.category,
                        data_json = EXCLUDED.data_json
                    """,
                    {
                        "event_id": event.event_id,
                        "user_id": event.user_id,
                        "source_kind": event.source_kind,
                        "source_id": event.source_id,
                        "sentiment": event.sentiment,
                        "category": event.category,
                        "data_json": Jsonb(event.model_dump(mode="json")),
                        "created_at": event.created_at,
                    },
                )
        return event.event_id

    def _branch_decision_id_for_idempotency(self, idempotency_key: str) -> str | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT decision_id FROM focus_branch_decision_events
                    WHERE idempotency_key = %s
                    """,
                    (idempotency_key,),
                )
                row = cur.fetchone()
        return None if row is None else str(row["decision_id"])

    def save_branch_decision_event(self, event: BranchDecisionEvent) -> str:
        if event.idempotency_key:
            existing_decision_id = self._branch_decision_id_for_idempotency(event.idempotency_key)
            if existing_decision_id is not None:
                if existing_decision_id != event.decision_id:
                    return existing_decision_id
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO focus_branch_decision_events (
                            decision_id, user_id, root_thread_id, source_thread_id,
                            branch_id, action, status, mode, score, threshold, signals,
                            rationale, request_id, trace_id, idempotency_key,
                            promoted_action_id, dismiss_reason, error, metadata,
                            data_json, created_at, updated_at, executed_at
                        ) VALUES (
                            %(decision_id)s, %(user_id)s, %(root_thread_id)s,
                            %(source_thread_id)s, %(branch_id)s, %(action)s, %(status)s,
                            %(mode)s, %(score)s, %(threshold)s, %(signals)s, %(rationale)s,
                            %(request_id)s, %(trace_id)s, %(idempotency_key)s,
                            %(promoted_action_id)s, %(dismiss_reason)s, %(error)s,
                            %(metadata)s, %(data_json)s, %(created_at)s, %(updated_at)s,
                            %(executed_at)s
                        )
                        ON CONFLICT (decision_id) DO UPDATE SET
                            user_id = EXCLUDED.user_id,
                            root_thread_id = EXCLUDED.root_thread_id,
                            source_thread_id = EXCLUDED.source_thread_id,
                            branch_id = EXCLUDED.branch_id,
                            action = EXCLUDED.action,
                            status = EXCLUDED.status,
                            mode = EXCLUDED.mode,
                            score = EXCLUDED.score,
                            threshold = EXCLUDED.threshold,
                            signals = EXCLUDED.signals,
                            rationale = EXCLUDED.rationale,
                            request_id = EXCLUDED.request_id,
                            trace_id = EXCLUDED.trace_id,
                            idempotency_key = EXCLUDED.idempotency_key,
                            promoted_action_id = EXCLUDED.promoted_action_id,
                            dismiss_reason = EXCLUDED.dismiss_reason,
                            error = EXCLUDED.error,
                            metadata = EXCLUDED.metadata,
                            data_json = EXCLUDED.data_json,
                            updated_at = EXCLUDED.updated_at,
                            executed_at = EXCLUDED.executed_at
                        """,
                        self._branch_decision_params(event),
                    )
        except psycopg.errors.UniqueViolation:
            if event.idempotency_key:
                existing_decision_id = self._branch_decision_id_for_idempotency(
                    event.idempotency_key
                )
                if existing_decision_id is not None:
                    return existing_decision_id
            raise
        return event.decision_id

    def get_branch_decision_event(self, decision_id: str) -> BranchDecisionEvent | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT {_BRANCH_DECISION_EVENT_COLUMNS}
                    FROM focus_branch_decision_events
                    WHERE decision_id = %s
                    """,
                    (decision_id,),
                )
                row = cur.fetchone()
        return None if row is None else self._branch_decision_from_row(row)

    def list_branch_decision_events(
        self,
        *,
        user_id: str | None = None,
        root_thread_id: str | None = None,
        source_thread_id: str | None = None,
        status: str | None = None,
        action: str | None = None,
        limit: int = 50,
    ) -> list[BranchDecisionEvent]:
        clauses: list[str] = []
        params: dict[str, object] = {"limit": max(0, limit)}
        if user_id is not None:
            clauses.append("(user_id IS NULL OR user_id = %(user_id)s)")
            params["user_id"] = user_id
        if root_thread_id is not None:
            clauses.append("root_thread_id = %(root_thread_id)s")
            params["root_thread_id"] = root_thread_id
        if source_thread_id is not None:
            clauses.append("source_thread_id = %(source_thread_id)s")
            params["source_thread_id"] = source_thread_id
        if status is not None:
            clauses.append("status = %(status)s")
            params["status"] = status
        if action is not None:
            clauses.append("action = %(action)s")
            params["action"] = action
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT {_BRANCH_DECISION_EVENT_COLUMNS}
                    FROM focus_branch_decision_events
                    {where}
                    ORDER BY created_at DESC, decision_id DESC
                    LIMIT %(limit)s
                    """,
                    params,
                )
                rows = cur.fetchall()
        return [self._branch_decision_from_row(row) for row in rows]

    def update_branch_decision_event(self, event: BranchDecisionEvent) -> BranchDecisionEvent:
        decision_id = self.save_branch_decision_event(event)
        stored = self.get_branch_decision_event(decision_id)
        return stored or event

    @staticmethod
    def _branch_decision_params(event: BranchDecisionEvent) -> dict[str, object]:
        return {
            "decision_id": event.decision_id,
            "user_id": event.user_id,
            "root_thread_id": event.root_thread_id,
            "source_thread_id": event.source_thread_id,
            "branch_id": event.branch_id,
            "action": event.action.value,
            "status": event.status.value,
            "mode": event.mode.value,
            "score": event.score,
            "threshold": event.threshold,
            "signals": Jsonb([item.model_dump(mode="json") for item in event.signals]),
            "rationale": event.rationale,
            "request_id": event.request_id,
            "trace_id": event.trace_id,
            "idempotency_key": event.idempotency_key,
            "promoted_action_id": event.promoted_action_id,
            "dismiss_reason": event.dismiss_reason,
            "error": event.error,
            "metadata": Jsonb(event.metadata),
            "data_json": Jsonb(event.model_dump(mode="json")),
            "created_at": event.created_at,
            "updated_at": event.updated_at,
            "executed_at": event.executed_at,
        }


__all__ = ["PostgresGovernanceRepository"]
