from __future__ import annotations

import hashlib
import json
from typing import Any

from .index import RetrievalDocument, RetrievalIndex, RetrievalSearchHit


def index_branch_decision_event(
    *,
    retrieval_index: RetrievalIndex | None,
    embedding_provider: Any | None,
    event: Any,
) -> bool:
    if retrieval_index is None or embedding_provider is None:
        return False
    text = _branch_event_text(event)
    if not text.strip():
        return False
    decision_id = str(getattr(event, "decision_id", "") or "")
    if not decision_id:
        return False
    retrieval_index.upsert(
        RetrievalDocument(
            collection="focus_branch_context",
            doc_id=f"branch:{decision_id}",
            source_id=decision_id,
            text=text,
            vector=embedding_provider.embed([text])[0],
            fields={
                "source_type": "branch_context",
                "decision_id": decision_id,
                "user_id": str(getattr(event, "user_id", "") or ""),
                "root_thread_id": str(getattr(event, "root_thread_id", "") or ""),
                "source_thread_id": str(getattr(event, "source_thread_id", "") or ""),
                "branch_id": str(getattr(event, "branch_id", "") or ""),
                "action": _value(getattr(event, "action", "")),
                "status": _value(getattr(event, "status", "")),
                "content_hash": hashlib.sha256(text.encode()).hexdigest(),
            },
        )
    )
    return True


class BranchContextRetrievalService:
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

    def search_similar_context(
        self,
        *,
        query: str,
        user_id: str | None,
        root_thread_id: str | None,
        limit: int = 5,
    ) -> list[RetrievalSearchHit]:
        if self.retrieval_index is None or self.embedding_provider is None:
            return []
        filters = {
            key: value
            for key, value in {
                "user_id": user_id or "",
                "root_thread_id": root_thread_id or "",
            }.items()
            if value
        }
        hits = self.retrieval_index.search(
            collection="focus_branch_context",
            query=query,
            vector=self.embedding_provider.embed([query])[0],
            limit=limit,
            filters=filters,
        )
        return [hit for hit in (_hydrate_hit(self.repository, hit) for hit in hits) if hit]


def _hydrate_hit(repository: Any | None, hit: RetrievalSearchHit) -> RetrievalSearchHit | None:
    if repository is None or not hasattr(repository, "get_branch_decision_event"):
        return hit
    event = repository.get_branch_decision_event(hit.source_id)
    if event is None:
        return None
    if str(getattr(event, "root_thread_id", "") or "") != str(hit.fields.get("root_thread_id") or ""):
        return None
    if str(getattr(event, "user_id", "") or "") != str(hit.fields.get("user_id") or ""):
        return None
    return RetrievalSearchHit(
        doc_id=hit.doc_id,
        source_id=hit.source_id,
        score=hit.score,
        text=hit.text,
        fields={
            **dict(hit.fields),
            "action": _value(getattr(event, "action", "")),
            "status": _value(getattr(event, "status", "")),
        },
    )


def _branch_event_text(event: Any) -> str:
    metadata = dict(getattr(event, "metadata", {}) or {})
    parts = [
        _value(getattr(event, "action", "")),
        _value(getattr(event, "status", "")),
        getattr(event, "rationale", ""),
        metadata.get("handoff_message"),
        metadata.get("handoff_message_preview"),
        json.dumps(metadata.get("diagnostic", {}) or {}, ensure_ascii=False, sort_keys=True),
    ]
    return "\n".join(str(part).strip() for part in parts if str(part).strip())


def _value(value: Any) -> str:
    return str(getattr(value, "value", value) or "")
