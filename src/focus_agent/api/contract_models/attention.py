from __future__ import annotations

from pydantic import BaseModel

from focus_agent.core.attention import (
    AttentionCursor,
    AttentionDiff,
    AttentionEvidence,
    AttentionItem,
    AttentionPolicy,
    AttentionReason,
    AttentionSnapshot,
    ResumePacket,
)


class AttentionReviewRequest(BaseModel):
    cursor: AttentionCursor


__all__ = [
    "AttentionReviewRequest",
    "AttentionCursor",
    "AttentionDiff",
    "AttentionEvidence",
    "AttentionItem",
    "AttentionPolicy",
    "AttentionReason",
    "AttentionSnapshot",
    "ResumePacket",
]
