"""State bookkeeping for model-written compaction summaries.

``build_incremental_compaction_update`` stays the base of every update: it owns
the message cursor, the history excerpts and the heuristic text used whenever no
model summary is available.  This module works out which messages a model
summary still has to absorb and lays an accepted summary over that base.  It
never calls a model itself.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .context_compaction import (
    SUMMARY_FALLBACK_REASON_KEY,
    SUMMARY_METHOD_KEY,
    _branch_id,
    _has_tool_calls,
    _message_stable_id,
    _message_text,
    state_compaction_boundary,
)
from .context_compaction_summary import _drift_report

MODEL_SUMMARY_KEY = "model_summary"
SUMMARY_METHOD_MODEL = "model"
SUMMARY_METHOD_HEURISTIC = "heuristic"


@dataclass(frozen=True, slots=True)
class PendingModelCompaction:
    """Messages that left the recent window since the last accepted model summary."""

    messages: tuple[Any, ...]
    previous_summary: str
    cursor: int
    cursor_id: str | None
    branch_id: str
    stored: Mapping[str, Any] | None = None


def pending_model_compaction(
    values: Mapping[str, Any], previous_meta: Mapping[str, Any]
) -> PendingModelCompaction:
    """Select what the next model summary must fold in.

    A stored model summary keeps its own cursor, so turns that fell back to the
    heuristic text are folded in on the next successful call instead of being
    lost.  Without one, the summary starts from the heuristic pass's cursor.
    """

    branch_id = _branch_id(values)
    stored = _stored_model_summary(previous_meta, branch_id=branch_id)
    previous_branch_id = str(previous_meta.get("source_branch_id") or "")
    branch_changed = bool(previous_branch_id) and previous_branch_id != branch_id
    if stored is not None:
        cursor_meta: Mapping[str, Any] = stored
    else:
        cursor_meta = {} if branch_changed else previous_meta
    boundary = state_compaction_boundary(values, cursor_meta)
    if not boundary.cursor_valid:
        stored, previous_summary = None, ""
    elif stored is not None:
        previous_summary = str(stored["text"])
    else:
        previous_summary = "" if branch_changed else _heuristic_summary(values, previous_meta)
    prefix_end = boundary.prefix_end
    return PendingModelCompaction(
        messages=tuple(
            message
            for message in boundary.source_messages[boundary.cursor : prefix_end]
            if _message_text(message).strip() or _has_tool_calls(message)
        ),
        previous_summary=previous_summary,
        cursor=prefix_end,
        cursor_id=(
            _message_stable_id(boundary.source_messages[prefix_end - 1], prefix_end - 1)
            if prefix_end > 0
            else None
        ),
        branch_id=branch_id,
        stored=stored,
    )


def model_summary_state(
    pending: PendingModelCompaction, *, text: str, model_id: str, written_at: str
) -> dict[str, Any]:
    return {
        "text": text,
        "source_message_cursor": pending.cursor,
        "source_message_cursor_id": pending.cursor_id,
        "source_branch_id": pending.branch_id,
        "model": model_id,
        "written_at": written_at,
    }


def with_model_summary(
    update: Mapping[str, Any],
    *,
    values: Mapping[str, Any],
    summary_state: Mapping[str, Any],
) -> dict[str, Any]:
    """Replace the heuristic text in ``update`` with an accepted model summary."""

    text = str(summary_state["text"])
    meta = dict(update.get("context_compaction") or {})
    if text != str(values.get("rolling_summary") or ""):
        meta["status"] = "updated"
        meta["no_gain"] = False
    meta.update(
        {
            SUMMARY_METHOD_KEY: SUMMARY_METHOD_MODEL,
            MODEL_SUMMARY_KEY: dict(summary_state),
            "history_summary": text,
            "after": {**dict(meta.get("after") or {}), "summary_chars": len(text)},
            "context_compaction_drift_report": _drift_report(values, text),
        }
    )
    return {**dict(update), "rolling_summary": text, "context_compaction": meta}


def with_heuristic_summary(
    update: Mapping[str, Any], *, fallback_reason: str = ""
) -> dict[str, Any]:
    meta = dict(update.get("context_compaction") or {})
    meta[SUMMARY_METHOD_KEY] = SUMMARY_METHOD_HEURISTIC
    if fallback_reason:
        meta[SUMMARY_FALLBACK_REASON_KEY] = fallback_reason
    return {**dict(update), "context_compaction": meta}


def _stored_model_summary(
    previous_meta: Mapping[str, Any], *, branch_id: str
) -> Mapping[str, Any] | None:
    stored = previous_meta.get(MODEL_SUMMARY_KEY)
    if not isinstance(stored, Mapping) or not str(stored.get("text") or "").strip():
        return None
    if str(stored.get("source_branch_id") or "") != branch_id:
        return None
    return stored


def _heuristic_summary(values: Mapping[str, Any], previous_meta: Mapping[str, Any]) -> str:
    """Text the previous heuristic pass kept for messages before its cursor."""

    if not previous_meta.get("compaction_version"):
        return str(values.get("rolling_summary") or "").strip()
    if not previous_meta.get("history_excerpts"):
        return ""
    return str(previous_meta.get("history_summary") or "").strip()


__all__ = [
    "MODEL_SUMMARY_KEY",
    "SUMMARY_METHOD_HEURISTIC",
    "SUMMARY_METHOD_MODEL",
    "PendingModelCompaction",
    "model_summary_state",
    "pending_model_compaction",
    "with_heuristic_summary",
    "with_model_summary",
]
