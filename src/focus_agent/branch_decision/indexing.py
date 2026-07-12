"""Branch decision retrieval and indexing helpers."""

from __future__ import annotations

from typing import Any

from focus_agent.core.governance import BranchDecisionEvent, BranchDecisionSignal
from focus_agent.retrieval.branch_context import (
    BranchContextRetrievalService,
    index_branch_decision_event,
)


def zvec_branch_context_shadow_signals(
    *,
    retrieval_index: Any | None,
    embedding_provider: Any | None,
    governance_repository: Any,
    message: str,
    user_id: str | None,
    root_thread_id: str | None,
) -> list[BranchDecisionSignal]:
    if retrieval_index is None or embedding_provider is None:
        return []
    try:
        hits = BranchContextRetrievalService(
            retrieval_index=retrieval_index,
            embedding_provider=embedding_provider,
            repository=governance_repository,
        ).search_similar_context(
            query=message,
            user_id=user_id,
            root_thread_id=root_thread_id,
            limit=3,
        )
    except Exception:  # noqa: BLE001
        return []
    if not hits:
        return []
    return [
        BranchDecisionSignal(
            name="zvec_branch_context",
            value={
                "mode": "shadow",
                "hit_count": len(hits),
                "top_score": hits[0].score,
                "source_ids": [hit.source_id for hit in hits],
            },
            score=hits[0].score,
            weight=0.0,
            evidence_refs=[hit.source_id for hit in hits],
            rationale="Zvec branch context shadow retrieval.",
        )
    ]


def index_branch_decision_best_effort(
    *,
    retrieval_index: Any | None,
    embedding_provider: Any | None,
    event: BranchDecisionEvent,
) -> None:
    try:
        index_branch_decision_event(
            retrieval_index=retrieval_index,
            embedding_provider=embedding_provider,
            event=event,
        )
    except Exception:  # noqa: BLE001
        return
