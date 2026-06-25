from __future__ import annotations

import hashlib
import json
from typing import Any

from .index import RetrievalDocument, RetrievalIndex, RetrievalSearchHit


def index_governance_feedback(
    *,
    retrieval_index: RetrievalIndex | None,
    embedding_provider: Any | None,
    item: Any,
) -> bool:
    if retrieval_index is None or embedding_provider is None:
        return False
    source_id, source_kind = _source_identity(item)
    if not source_id:
        return False
    text = _feedback_text(item)
    if not text.strip():
        return False
    retrieval_index.upsert(
        RetrievalDocument(
            collection="focus_governance_feedback",
            doc_id=f"governance:{source_kind}:{source_id}",
            source_id=source_id,
            text=text,
            vector=embedding_provider.embed([text])[0],
            fields={
                "source_type": "governance_feedback",
                "source_kind": source_kind,
                "user_id": str(getattr(item, "user_id", "") or ""),
                "feedback": str(getattr(item, "feedback", "") or ""),
                "sentiment": str(getattr(item, "sentiment", "") or ""),
                "category": str(getattr(item, "category", "") or ""),
                "content_hash": hashlib.sha256(text.encode()).hexdigest(),
            },
        )
    )
    return True


class GovernanceFeedbackRetrievalService:
    def __init__(
        self,
        *,
        retrieval_index: RetrievalIndex | None,
        embedding_provider: Any | None,
        repository: Any | None = None,
    ) -> None:
        self.retrieval_index = retrieval_index
        self.embedding_provider = embedding_provider
        self.repository = repository

    def search_feedback(
        self,
        *,
        query: str,
        user_id: str | None = None,
        limit: int = 5,
    ) -> list[RetrievalSearchHit]:
        if self.retrieval_index is None or self.embedding_provider is None:
            return []
        filters = {"user_id": user_id} if user_id else None
        hits = self.retrieval_index.search(
            collection="focus_governance_feedback",
            query=query,
            vector=self.embedding_provider.embed([query])[0],
            limit=limit,
            filters=filters,
        )
        return [
            hit
            for hit in (
                _hydrate_governance_hit(self.repository, hit, user_id=user_id) for hit in hits
            )
            if hit is not None
        ]


def _source_identity(item: Any) -> tuple[str, str]:
    for attr, kind in (
        ("selection_id", "skill_selection"),
        ("evidence_id", "context_evidence"),
        ("event_id", "feedback"),
    ):
        value = str(getattr(item, attr, "") or "")
        if value:
            return value, kind
    return "", item.__class__.__name__.lower()


def _feedback_text(item: Any) -> str:
    parts = [
        getattr(item, "message_preview", ""),
        getattr(item, "rationale", ""),
        getattr(item, "feedback", ""),
        getattr(item, "feedback_reason", ""),
        getattr(item, "sentiment", ""),
        getattr(item, "category", ""),
        json.dumps(getattr(item, "selected_memories", []) or [], ensure_ascii=False, sort_keys=True),
        json.dumps(getattr(item, "excluded_memories", []) or [], ensure_ascii=False, sort_keys=True),
        json.dumps(getattr(item, "drift_report", {}) or {}, ensure_ascii=False, sort_keys=True),
        json.dumps(getattr(item, "user_override", {}) or {}, ensure_ascii=False, sort_keys=True),
        json.dumps(getattr(item, "metadata", {}) or {}, ensure_ascii=False, sort_keys=True),
        " ".join(getattr(item, "activated_skill_ids", []) or []),
        " ".join(getattr(item, "matched_triggers", []) or []),
    ]
    return "\n".join(str(part).strip() for part in parts if str(part).strip())


def _hydrate_governance_hit(
    repository: Any | None,
    hit: RetrievalSearchHit,
    *,
    user_id: str | None,
) -> RetrievalSearchHit | None:
    if repository is None:
        return hit
    source_kind = str(hit.fields.get("source_kind") or "")
    item = _governance_item(repository, source_kind=source_kind, source_id=hit.source_id)
    if item is None:
        return None
    item_user_id = str(getattr(item, "user_id", "") or "")
    if user_id and item_user_id not in {"", user_id}:
        return None
    return RetrievalSearchHit(
        doc_id=hit.doc_id,
        source_id=hit.source_id,
        score=hit.score,
        text=hit.text,
        fields={**dict(hit.fields), "user_id": item_user_id},
    )


def _governance_item(repository: Any, *, source_kind: str, source_id: str) -> Any | None:
    if source_kind == "skill_selection":
        get_event = getattr(repository, "get_skill_selection_event", None)
        if callable(get_event):
            return get_event(source_id)
    if source_kind == "context_evidence":
        return _find_listed_item(
            getattr(repository, "list_context_evidence", None),
            source_id=source_id,
            id_attr="evidence_id",
        )
    if source_kind == "feedback":
        return _find_listed_item(
            getattr(repository, "list_feedback_events", None),
            source_id=source_id,
            id_attr="event_id",
        )
    return None


def _find_listed_item(method: Any, *, source_id: str, id_attr: str) -> Any | None:
    if not callable(method):
        return None
    try:
        items = method(limit=1000)
    except Exception:  # noqa: BLE001
        return None
    for item in items:
        if str(getattr(item, id_attr, "") or "") == source_id:
            return item
    return None
