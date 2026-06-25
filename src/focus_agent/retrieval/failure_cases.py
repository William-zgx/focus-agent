from __future__ import annotations

import hashlib
import json
from typing import Any

from .index import RetrievalDocument, RetrievalIndex, RetrievalSearchHit


def index_failure_case_from_trajectory(
    *,
    retrieval_index: RetrievalIndex | None,
    embedding_provider: Any | None,
    record: Any,
) -> bool:
    if retrieval_index is None or embedding_provider is None:
        return False
    status = str(getattr(record, "status", "") or "").lower()
    has_step_error = any(str(getattr(step, "error", "") or "").strip() for step in getattr(record, "trajectory", []) or [])
    if status not in {"failed", "error"} and not has_step_error and not getattr(record, "error", None):
        return False
    turn_id = str(getattr(record, "id", "") or "")
    if not turn_id:
        return False
    text = _failure_text(record)
    retrieval_index.upsert(
        RetrievalDocument(
            collection="focus_failure_cases",
            doc_id=f"failure:{turn_id}",
            source_id=turn_id,
            text=text,
            vector=embedding_provider.embed([text])[0],
            fields={
                "source_type": "failure_case",
                "turn_id": turn_id,
                "root_thread_id": str(getattr(record, "root_thread_id", "") or ""),
                "thread_id": str(getattr(record, "thread_id", "") or ""),
                "status": status,
                "workspace_root": str((getattr(record, "plan_meta", {}) or {}).get("workspace_root") or ""),
                "content_hash": hashlib.sha256(text.encode()).hexdigest(),
            },
        )
    )
    return True


class FailureCaseRetrievalService:
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

    def search_recovery_cases(
        self,
        *,
        query: str,
        root_thread_id: str | None = None,
        workspace_root: str | None = None,
        limit: int = 5,
    ) -> list[RetrievalSearchHit]:
        if self.retrieval_index is None or self.embedding_provider is None:
            return []
        filters = {}
        if root_thread_id:
            filters["root_thread_id"] = root_thread_id
        if workspace_root:
            filters["workspace_root"] = workspace_root
        hits = self.retrieval_index.search(
            collection="focus_failure_cases",
            query=query,
            vector=self.embedding_provider.embed([query])[0],
            limit=limit,
            filters=filters,
        )
        return [
            hit
            for hit in (
                _hydrate_failure_hit(
                    self.repository,
                    hit,
                    root_thread_id=root_thread_id,
                    workspace_root=workspace_root,
                )
                for hit in hits
            )
            if hit is not None
        ]


def _failure_text(record: Any) -> str:
    parts = [
        getattr(record, "task_brief", ""),
        getattr(record, "user_message", ""),
        getattr(record, "answer", ""),
        getattr(record, "error", ""),
        json.dumps(getattr(record, "plan_meta", {}) or {}, ensure_ascii=False, sort_keys=True),
    ]
    for step in getattr(record, "trajectory", []) or []:
        parts.extend(
            [
                getattr(step, "tool", ""),
                json.dumps(getattr(step, "args", {}) or {}, ensure_ascii=False, sort_keys=True),
                getattr(step, "observation", ""),
                getattr(step, "error", ""),
            ]
        )
    return "\n".join(str(part).strip() for part in parts if str(part).strip())


def _hydrate_failure_hit(
    repository: Any | None,
    hit: RetrievalSearchHit,
    *,
    root_thread_id: str | None,
    workspace_root: str | None,
) -> RetrievalSearchHit | None:
    if repository is None or not hasattr(repository, "get_turn"):
        return hit
    record = repository.get_turn(hit.source_id)
    if record is None:
        return None
    if root_thread_id and str(getattr(record, "root_thread_id", "") or "") != root_thread_id:
        return None
    record_workspace = str((getattr(record, "plan_meta", {}) or {}).get("workspace_root") or "")
    if workspace_root and record_workspace != workspace_root:
        return None
    status = str(getattr(record, "status", "") or "").lower()
    has_step_error = any(
        str(getattr(step, "error", "") or "").strip()
        for step in getattr(record, "trajectory", []) or []
    )
    if status not in {"failed", "error"} and not has_step_error and not getattr(record, "error", None):
        return None
    return RetrievalSearchHit(
        doc_id=hit.doc_id,
        source_id=hit.source_id,
        score=hit.score,
        text=hit.text,
        fields={
            **dict(hit.fields),
            "root_thread_id": str(getattr(record, "root_thread_id", "") or ""),
            "workspace_root": record_workspace,
            "status": status,
        },
    )
