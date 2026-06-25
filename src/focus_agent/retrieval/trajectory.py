from __future__ import annotations

import hashlib
import json
from typing import Any

from .failure_cases import index_failure_case_from_trajectory
from .index import RetrievalDocument, RetrievalIndex, RetrievalSearchHit


def index_trajectory_record(
    *,
    retrieval_index: RetrievalIndex | None,
    embedding_provider: Any | None,
    record: Any,
) -> None:
    if retrieval_index is None or embedding_provider is None:
        return
    turn_id = str(getattr(record, "id", "") or "")
    if not turn_id:
        return
    _upsert_text(
        retrieval_index=retrieval_index,
        embedding_provider=embedding_provider,
        doc_id=f"trajectory:{turn_id}:turn",
        source_id=turn_id,
        text=_turn_text(record),
        fields=_turn_fields(record),
    )
    for index, step in enumerate(list(getattr(record, "trajectory", []) or [])):
        _upsert_text(
            retrieval_index=retrieval_index,
            embedding_provider=embedding_provider,
            doc_id=f"trajectory:{turn_id}:step:{index}",
            source_id=turn_id,
            text=_step_text(step),
            fields={**_turn_fields(record), "step_index": index, "tool": getattr(step, "tool", "")},
        )
    try:
        index_failure_case_from_trajectory(
            retrieval_index=retrieval_index,
            embedding_provider=embedding_provider,
            record=record,
        )
    except Exception:  # noqa: BLE001
        return


def search_trajectory(
    *,
    retrieval_index: RetrievalIndex | None,
    embedding_provider: Any | None,
    query: str,
    limit: int = 5,
) -> list[RetrievalSearchHit]:
    if retrieval_index is None or embedding_provider is None:
        return []
    vector = embedding_provider.embed([query])[0]
    return retrieval_index.search(
        collection="focus_trajectory",
        query=query,
        vector=vector,
        limit=limit,
    )


def _upsert_text(
    *,
    retrieval_index: RetrievalIndex,
    embedding_provider: Any,
    doc_id: str,
    source_id: str,
    text: str,
    fields: dict[str, object],
) -> None:
    if not text.strip():
        return
    try:
        retrieval_index.upsert(
            RetrievalDocument(
                collection="focus_trajectory",
                doc_id=doc_id,
                source_id=source_id,
                text=text,
                vector=embedding_provider.embed([text])[0],
                fields={
                    **fields,
                    "source_type": "trajectory",
                    "content_hash": hashlib.sha256(text.encode()).hexdigest(),
                },
            )
        )
    except Exception:  # noqa: BLE001
        return


def _turn_text(record: Any) -> str:
    parts = [
        getattr(record, "task_brief", None),
        getattr(record, "user_message", None),
        getattr(record, "answer", None),
        getattr(record, "error", None),
        json.dumps(getattr(record, "plan_meta", {}) or {}, ensure_ascii=False, sort_keys=True),
    ]
    return "\n".join(str(part).strip() for part in parts if str(part).strip())


def _step_text(step: Any) -> str:
    parts = [
        getattr(step, "tool", None),
        json.dumps(getattr(step, "args", {}) or {}, ensure_ascii=False, sort_keys=True),
        getattr(step, "observation", None),
        getattr(step, "error", None),
    ]
    return "\n".join(str(part).strip() for part in parts if str(part).strip())


def _turn_fields(record: Any) -> dict[str, object]:
    return {
        "turn_id": str(getattr(record, "id", "") or ""),
        "thread_id": str(getattr(record, "thread_id", "") or ""),
        "root_thread_id": str(getattr(record, "root_thread_id", "") or ""),
        "status": str(getattr(record, "status", "") or ""),
        "kind": str(getattr(record, "kind", "") or ""),
        "scene": str(getattr(record, "scene", "") or ""),
    }
