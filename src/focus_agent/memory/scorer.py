from __future__ import annotations

from ..core.types import PromptMode
from .models import MemorySearchHit, MemoryWriteRequest


def score_memory_hit(hit: MemorySearchHit, *, query: str, prompt_mode: PromptMode) -> float:
    score = hit.score
    score += hit.record.importance * 0.35
    if hit.record.confidence is not None:
        score += hit.record.confidence * 0.2
    if hit.matched_terms:
        score += min(len(hit.matched_terms), 4) * 0.1
    if prompt_mode == PromptMode.BRANCH_REVIEW and hit.record.promoted_to_main:
        score += 0.15
    if prompt_mode == PromptMode.SYNTHESIZE and hit.record.source_branch_id and not hit.record.promoted_to_main:
        score -= 0.25
    if query and hit.record.summary and query.casefold() in hit.record.summary.casefold():
        score += 0.2
    return round(score, 4)


def score_memory_importance(record: MemoryWriteRequest, *, state: dict) -> float:
    score = record.importance
    score += min(len(record.evidence_refs), 3) * 0.08
    if record.visibility.value == "shared":
        score += 0.12
    if record.visibility.value == "promotable":
        score += 0.08
    if state.get("active_goal") and state.get("active_goal") in record.content:
        score += 0.1
    return max(0.0, min(1.0, round(score, 4)))
