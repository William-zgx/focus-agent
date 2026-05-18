from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from focus_agent.core.agent_team import (
    AgentTeamMergeReview,
    AgentTeamMergeReviewEvent,
    AgentTeamMergeReviewStatus,
)

from .agent_team_helpers import _now


def _capture_merge_review_payload(review: AgentTeamMergeReview) -> dict[str, Any]:
    return {
        "review_id": review.review_id,
        "session_id": review.session_id,
        "source_kind": "agent_team_merge_review",
        "source_id": review.review_id,
        "summary": review.summary or review.title or "Agent Team merge review",
        "changed_files": review.changed_files,
        "test_evidence": review.test_evidence,
        "status": "stub",
    }


def _merge_review_event(
    *,
    review: AgentTeamMergeReview,
    event_type: str,
    message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AgentTeamMergeReviewEvent:
    return AgentTeamMergeReviewEvent(
        event_id=str(uuid4()),
        review_id=review.review_id,
        session_id=review.session_id,
        event_type=event_type,
        status=review.status,
        message=message,
        metadata=dict(metadata or {}),
        created_at=_now(),
    )


def _merge_review_apply_conflict(
    review: AgentTeamMergeReview,
    *,
    check: dict[str, Any],
    target_root: Path,
) -> AgentTeamMergeReview:
    return review.model_copy(
        update={
            "status": AgentTeamMergeReviewStatus.CONFLICT,
            "conflict_files": list(check["files"]),
            "error_message": check["message"],
            "apply_target_path": str(target_root),
            "updated_at": _now(),
        }
    )


def _merge_review_apply_error(
    review: AgentTeamMergeReview,
    *,
    apply_result: dict[str, Any],
    target_root: Path,
) -> AgentTeamMergeReview:
    return review.model_copy(
        update={
            "status": AgentTeamMergeReviewStatus.ERROR,
            "error_message": apply_result["message"],
            "apply_target_path": str(target_root),
            "updated_at": _now(),
        }
    )


def _merge_review_applied(
    review: AgentTeamMergeReview,
    *,
    target_root: Path,
) -> AgentTeamMergeReview:
    return review.model_copy(
        update={
            "status": AgentTeamMergeReviewStatus.APPLIED,
            "apply_target_path": str(target_root),
            "error_message": None,
            "applied_at": _now(),
            "updated_at": _now(),
        }
    )


__all__ = [
    "_capture_merge_review_payload",
    "_merge_review_applied",
    "_merge_review_apply_conflict",
    "_merge_review_apply_error",
    "_merge_review_event",
]
