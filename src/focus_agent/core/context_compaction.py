"""Small, structural context-compaction primitives.

This module deliberately does not summarize with a model.  It keeps an
append-only message cursor, renders the current authoritative state fields,
and leaves the most recent messages to the normal prompt assembly path.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .context_token_counting import estimate_message_token_count
from .types import ContextBudget

DEFAULT_RECENT_MESSAGE_LIMIT = 12
MAX_HISTORY_EXCERPTS = 24
MAX_SECTION_ITEMS = 8
MAX_ITEM_CHARS = 320
COMPACTION_VERSION = 2


@dataclass(frozen=True, slots=True)
class CompactionBoundary:
    """The append-only boundary shared by prompt assembly and compaction."""

    source_messages: tuple[Any, ...]
    recent_messages: tuple[Any, ...]
    prefix_end: int
    cursor: int
    cursor_valid: bool
    cursor_id: str | None
    recent_limit: int
    recent_token_limit: int | None = None
    recent_token_count: int = 0


def select_recent_messages(
    state_or_messages: Mapping[str, Any] | Sequence[Any],
    *,
    limit: int | None = None,
    token_limit: int | None = None,
) -> list[Any]:
    """Return the same recent raw window that incremental compaction excludes."""

    messages = _source_messages(state_or_messages)
    recent_token_limit = token_limit
    budget = None
    if isinstance(state_or_messages, Mapping):
        if limit is None:
            limit = _recent_limit(state_or_messages)
        if recent_token_limit is None:
            recent_token_limit = _recent_token_limit(state_or_messages)
        budget = _context_budget(state_or_messages.get("context_budget"))
    boundary = compaction_message_boundary(
        messages,
        recent_limit=limit,
        recent_token_limit=recent_token_limit,
        budget=budget,
    )
    return list(boundary.recent_messages)


def compaction_message_boundary(
    messages: Sequence[Any],
    *,
    recent_limit: int | None = None,
    recent_token_limit: int | None = None,
    budget: ContextBudget | None = None,
    cursor_meta: Mapping[str, Any] | None = None,
) -> CompactionBoundary:
    """Resolve a stable append cursor without hashing message contents.

    The fallback cursor is an append index.  When a message exposes a stable
    ``id``/``message_id`` it is stored alongside that index, allowing a reset
    when a checkpoint no longer has the same message at the boundary.
    """

    source_messages = tuple(messages)
    limit = _coerce_recent_limit(recent_limit)
    token_limit = _coerce_token_limit(recent_token_limit)
    resolved_budget = budget or ContextBudget()
    prefix_end = _safe_prefix_end(
        source_messages,
        limit,
        recent_token_limit=token_limit,
        budget=resolved_budget,
    )
    previous = cursor_meta or {}
    try:
        previous_cursor = max(0, int(previous.get("source_message_cursor") or 0))
    except (TypeError, ValueError):
        previous_cursor = 0
    previous_cursor_id = str(previous.get("source_message_cursor_id") or "").strip() or None
    cursor_valid = previous_cursor <= prefix_end
    if cursor_valid and previous_cursor > 0 and previous_cursor <= len(source_messages):
        cursor_valid = _message_stable_id(
            source_messages[previous_cursor - 1], previous_cursor - 1
        ) == (previous_cursor_id or f"cursor:{previous_cursor - 1}")
    cursor = previous_cursor if cursor_valid else 0
    cursor_id = _message_stable_id(source_messages[cursor - 1], cursor - 1) if cursor > 0 else None
    return CompactionBoundary(
        source_messages=source_messages,
        recent_messages=source_messages[prefix_end:],
        prefix_end=prefix_end,
        cursor=cursor,
        cursor_valid=cursor_valid,
        cursor_id=cursor_id,
        recent_limit=limit,
        recent_token_limit=token_limit,
        recent_token_count=_message_token_count(source_messages[prefix_end:], resolved_budget),
    )


def build_incremental_compaction_update(
    values: Mapping[str, Any],
    previous_meta: Mapping[str, Any] | None = None,
    *,
    trigger: str = "manual",
    force: bool = False,
    now: str | None = None,
) -> dict[str, Any]:
    """Build a non-destructive structured summary from current state.

    ``rolling_summary`` is rebuilt from authoritative fields on every source
    change.  Only the message prefix before the recent raw window is retained
    as traceable excerpts; the old summary is never parsed as a source of
    constraints or findings.
    """

    current = dict(values)
    previous = dict(previous_meta or {})
    branch_id = _branch_id(current)
    branch_changed = bool(previous.get("source_branch_id")) and (
        str(previous.get("source_branch_id")) != branch_id
    )
    cursor_meta = {} if branch_changed else previous
    boundary = compaction_message_boundary(
        _source_messages(current),
        recent_limit=_recent_limit(current),
        recent_token_limit=_recent_token_limit(current),
        budget=_context_budget(current.get("context_budget")),
        cursor_meta=cursor_meta,
    )

    old_summary = str(current.get("rolling_summary") or "")
    old_history = (
        [] if branch_changed or not boundary.cursor_valid else _history_from_meta(previous)
    )
    if old_summary and not branch_changed and not previous.get("compaction_version"):
        old_history = [*_legacy_summary_excerpts(old_summary), *old_history]
    new_history = [
        _message_excerpt(message, index)
        for index, message in enumerate(
            boundary.source_messages[boundary.cursor : boundary.prefix_end],
            start=boundary.cursor,
        )
        if _message_text(message).strip()
    ]
    history = _merge_history(old_history, new_history)
    omitted_history = int(previous.get("history_omitted_count") or 0)
    if len(history) > MAX_HISTORY_EXCERPTS:
        omitted_history += len(history) - MAX_HISTORY_EXCERPTS
        history = history[-MAX_HISTORY_EXCERPTS:]

    source_cursors = _source_cursors(current, message_count=len(boundary.source_messages))
    source_scalars = {
        "active_goal": _text(current.get("active_goal")),
        "branch_id": branch_id,
    }
    source_changed = (
        branch_changed
        or not previous
        or dict(previous.get("source_state_cursors") or {}) != source_cursors
        or dict(previous.get("source_scalar_values") or {}) != source_scalars
        or bool(new_history)
        or not boundary.cursor_valid
    )

    summary = _render_summary(
        current,
        history=history,
        boundary=boundary,
        omitted_history=omitted_history,
    )
    history_summary = _render_history_summary(
        history=history,
        boundary=boundary,
        omitted_history=omitted_history,
    )
    summary_changed = summary != old_summary
    status = "updated" if source_changed or summary_changed or force else "no_gain"
    timestamp = now or datetime.now(UTC).isoformat()
    current_message_ids = [
        _message_stable_id(message, index)
        for index, message in enumerate(boundary.recent_messages, start=boundary.prefix_end)
    ]
    source_message_tail_id = (
        _message_stable_id(boundary.source_messages[-1], len(boundary.source_messages) - 1)
        if boundary.source_messages
        else None
    )
    metadata = {
        **previous,
        "compaction_version": COMPACTION_VERSION,
        "trigger": trigger,
        "status": status,
        "no_gain": status == "no_gain",
        "non_destructive": True,
        "source_branch_id": branch_id,
        "source_message_cursor": boundary.prefix_end,
        "source_message_cursor_id": (
            _message_stable_id(
                boundary.source_messages[boundary.prefix_end - 1], boundary.prefix_end - 1
            )
            if boundary.prefix_end > 0
            else None
        ),
        "source_message_cursor_kind": "append_index_with_message_id",
        "source_message_count": len(boundary.source_messages),
        "source_message_tail_id": source_message_tail_id,
        "recent_message_ids": current_message_ids,
        "recent_message_count": len(boundary.recent_messages),
        "recent_message_limit": boundary.recent_limit,
        "recent_token_limit": boundary.recent_token_limit,
        "recent_token_count": boundary.recent_token_count,
        "recent_selection_mode": (
            "message_count+token_budget+complete_turn"
            if boundary.recent_token_limit is not None
            else "message_count+complete_turn"
        ),
        "source_cursor_valid": boundary.cursor_valid,
        "source_cursor_reset": branch_changed or not boundary.cursor_valid,
        "source_state_cursors": source_cursors,
        "source_scalar_values": source_scalars,
        "history_excerpts": history,
        "history_summary": history_summary,
        "history_omitted_count": omitted_history,
        "legacy_summary_preserved": bool(
            old_summary and not branch_changed and not previous.get("compaction_version")
        ),
        "legacy_summary_chars": len(old_summary)
        if old_summary and not previous.get("compaction_version")
        else 0,
        "omitted_counts": _omitted_counts(
            current, history=history, omitted_history=omitted_history
        ),
        "before": {
            "summary_chars": len(old_summary),
            "source_message_cursor": _previous_cursor(previous),
            "source_message_count": int(previous.get("source_message_count") or 0),
        },
        "after": {
            "summary_chars": len(summary),
            "source_message_cursor": boundary.prefix_end,
            "source_message_count": len(boundary.source_messages),
        },
    }
    if status != "no_gain" or not previous.get("last_compacted_at"):
        metadata["last_compacted_at"] = timestamp
    metadata["context_compaction_drift_report"] = _drift_report(current, summary)
    return {"rolling_summary": summary, "context_compaction": metadata}


def _source_messages(state_or_messages: Mapping[str, Any] | Sequence[Any]) -> list[Any]:
    if not isinstance(state_or_messages, Mapping):
        return list(state_or_messages)
    messages = list(
        state_or_messages.get("messages") or state_or_messages.get("recent_messages") or []
    )
    values = dict(state_or_messages)
    from .branch_messages import branch_context_messages

    return list(branch_context_messages(messages, values=values))


def _recent_limit(values: Mapping[str, Any]) -> int:
    budget = values.get("context_budget")
    if isinstance(budget, Mapping):
        return _coerce_recent_limit(budget.get("recent_message_limit"))
    return _coerce_recent_limit(getattr(budget, "recent_message_limit", None))


def _recent_token_limit(values: Mapping[str, Any]) -> int | None:
    budget = _context_budget(values.get("context_budget"))
    return _coerce_token_limit(budget.recent_message_token_limit)


def _coerce_recent_limit(value: Any) -> int:
    try:
        return max(1, min(64, int(value or DEFAULT_RECENT_MESSAGE_LIMIT)))
    except (TypeError, ValueError):
        return DEFAULT_RECENT_MESSAGE_LIMIT


def _coerce_token_limit(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return max(1, min(1_000_000, int(value)))
    except (TypeError, ValueError):
        return None


def _context_budget(value: Any) -> ContextBudget:
    if isinstance(value, ContextBudget):
        return value
    if isinstance(value, Mapping):
        try:
            return ContextBudget.model_validate(dict(value))
        except Exception:  # noqa: BLE001
            return ContextBudget()
    return ContextBudget()


def _safe_prefix_end(
    messages: Sequence[Any],
    recent_limit: int,
    *,
    recent_token_limit: int | None = None,
    budget: ContextBudget | None = None,
) -> int:
    count_boundary = max(0, len(messages) - _coerce_recent_limit(recent_limit))
    token_boundary = 0
    if recent_token_limit is not None:
        token_boundary = len(messages)
        total = 0
        for index in range(len(messages) - 1, -1, -1):
            units = _message_token_count([messages[index]], budget or ContextBudget())
            if token_boundary < len(messages) and total + units > recent_token_limit:
                break
            total += units
            token_boundary = index
    return _complete_turn_boundary(messages, max(count_boundary, token_boundary))


def _complete_turn_boundary(messages: Sequence[Any], boundary: int) -> int:
    """Start recent context at a human/system turn, never inside tool output."""
    boundary = max(0, min(len(messages), boundary))
    while boundary > 0:
        current = messages[boundary]
        previous = messages[boundary - 1]
        if _is_tool_message(current) or _is_ai_message(current) or _has_tool_calls(previous):
            boundary -= 1
            continue
        break
    return boundary


def _message_stable_id(message: Any, index: int) -> str:
    if isinstance(message, Mapping):
        value = message.get("id") or message.get("message_id")
    else:
        value = getattr(message, "id", None) or getattr(message, "message_id", None)
    text = str(value or "").strip()
    return text if text else f"cursor:{index}"


def _message_type(message: Any) -> str:
    if isinstance(message, Mapping):
        return str(message.get("type") or message.get("role") or "message").strip().lower()
    return (
        str(
            getattr(message, "type", message.__class__.__name__.replace("Message", "message"))
            or "message"
        )
        .strip()
        .lower()
    )


def _is_tool_message(message: Any) -> bool:
    return _message_type(message) in {"tool", "toolmessage"}


def _is_ai_message(message: Any) -> bool:
    return _message_type(message) in {"ai", "assistant", "aimessage", "assistantmessage"}


def _has_tool_calls(message: Any) -> bool:
    if isinstance(message, Mapping):
        return bool(message.get("tool_calls"))
    return bool(getattr(message, "tool_calls", None))


def _message_token_count(messages: Sequence[Any], budget: ContextBudget) -> int:
    return sum(
        max(1, int(estimate_message_token_count(message, budget=budget).tokens))
        for message in messages
    )


def _message_text(message: Any) -> str:
    content = (
        message.get("content", "")
        if isinstance(message, Mapping)
        else getattr(message, "content", "")
    )
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, Mapping):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return " ".join(part for part in parts if part).strip()
    return str(content or "").strip()


def _message_excerpt(message: Any, index: int) -> dict[str, Any]:
    return {
        "id": _message_stable_id(message, index),
        "cursor": index,
        "role": _message_type(message),
        "text": _clip(_message_text(message), MAX_ITEM_CHARS),
    }


def _history_from_meta(meta: Mapping[str, Any]) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    for raw in list(meta.get("history_excerpts") or []):
        if not isinstance(raw, Mapping):
            continue
        text = _clip(raw.get("text"), MAX_ITEM_CHARS)
        if not text:
            continue
        history.append(
            {
                "id": str(raw.get("id") or "").strip(),
                "cursor": raw.get("cursor"),
                "role": str(raw.get("role") or "message"),
                "text": text,
            }
        )
    return history


def _legacy_summary_excerpts(summary: str) -> list[dict[str, Any]]:
    compact = str(summary or "").strip()
    if not compact:
        return []
    return [
        {
            "id": f"legacy-summary:{index}",
            "cursor": None,
            "role": "legacy_summary_unverified",
            "text": _clip(compact[start : start + MAX_ITEM_CHARS], MAX_ITEM_CHARS),
        }
        for index, start in enumerate(range(0, len(compact), MAX_ITEM_CHARS))
    ]


def _merge_history(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in [*old, *new]:
        key = str(item.get("id") or f"cursor:{item.get('cursor')}")
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def _source_cursors(values: Mapping[str, Any], *, message_count: int) -> dict[str, int]:
    return {
        "messages": message_count,
        **{
            key: len(list(values.get(key, []) or []))
            for key in (
                "user_constraints",
                "pinned_facts",
                "pinned_items",
                "imported_findings",
                "branch_local_findings",
                "artifacts",
                "citations",
            )
        },
    }


def _previous_cursor(meta: Mapping[str, Any]) -> int:
    try:
        return max(0, int(meta.get("source_message_cursor") or 0))
    except (TypeError, ValueError):
        return 0


def _branch_id(values: Mapping[str, Any]) -> str:
    branch_meta = values.get("branch_meta")
    if not isinstance(branch_meta, Mapping):
        return ""
    return str(branch_meta.get("branch_id") or "").strip()


def _item_text(item: Any, *keys: str) -> str:
    if isinstance(item, Mapping):
        for key in keys:
            value = item.get(key)
            if value:
                return str(value).strip()
        return ""
    for key in keys:
        value = getattr(item, key, None)
        if value:
            return str(value).strip()
    return ""


def _item_refs(item: Any) -> list[str]:
    raw = (
        item.get("evidence_refs")
        if isinstance(item, Mapping)
        else getattr(item, "evidence_refs", [])
    )
    return [str(value).strip() for value in list(raw or []) if str(value).strip()]


def _format_finding(item: Any) -> str:
    text = _item_text(item, "finding", "summary", "content")
    refs = _item_refs(item)
    if refs:
        text = f"{text} [evidence: {', '.join(refs)}]"
    return _clip(text, MAX_ITEM_CHARS)


def _format_artifact(item: Any) -> str:
    title = _item_text(item, "title", "artifact_id", "summary")
    ref = _item_text(item, "uri", "artifact_id", "source_artifact_id")
    if title and ref and ref not in title:
        return _clip(f"{title} ({ref})", MAX_ITEM_CHARS)
    return _clip(title or ref, MAX_ITEM_CHARS)


def _take_lines(items: Any, formatter, *, limit: int = MAX_SECTION_ITEMS) -> tuple[list[str], int]:
    raw_items = list(items or [])
    lines = [line for item in raw_items[-limit:] if (line := formatter(item))]
    return lines, max(0, len(raw_items) - len(lines))


def _render_summary(
    values: Mapping[str, Any],
    *,
    history: list[dict[str, Any]],
    boundary: CompactionBoundary,
    omitted_history: int,
) -> str:
    lines = [
        "Context compaction snapshot:",
        (
            f"Coverage: source messages {boundary.prefix_end}/{len(boundary.source_messages)}; "
            f"recent raw messages kept separately ({len(boundary.recent_messages)} messages, "
            f"{boundary.recent_token_count} estimated tokens)."
        ),
    ]
    active_goal = _text(values.get("active_goal"))
    if active_goal:
        lines.append(f"Goal: {active_goal}")

    constraints, omitted_constraints = _take_lines(
        values.get("user_constraints"), lambda item: _item_text(item, "constraint", "content")
    )
    if constraints:
        lines.append("Constraints:")
        lines.extend(f"- {line}" for line in constraints)

    pinned, omitted_pinned = _take_lines(
        values.get("pinned_facts"), lambda item: _item_text(item, "fact", "content")
    )
    if pinned:
        lines.append("Pinned facts:")
        lines.extend(f"- {line}" for line in pinned)

    approved, omitted_approved = _take_lines(values.get("imported_findings"), _format_finding)
    if approved:
        lines.append("Approved findings:")
        lines.extend(f"- {line}" for line in approved)

    local, omitted_local = _take_lines(values.get("branch_local_findings"), _format_finding)
    if local:
        lines.append("Local findings pending review:")
        lines.extend(f"- {line}" for line in local)

    artifact_lines, omitted_artifacts = _take_lines(values.get("artifacts"), _format_artifact)
    citation_lines, omitted_citations = _take_lines(values.get("citations"), _format_artifact)
    if artifact_lines or citation_lines:
        lines.append("Evidence and artifact refs:")
        lines.extend(f"- {line}" for line in [*artifact_lines, *citation_lines])

    if history:
        if any(item.get("role") == "legacy_summary_unverified" for item in history):
            lines.append("Legacy summary excerpts (unparsed; not authoritative):")
            lines.extend(
                f"- [{item['id']}] {item['text']}"
                for item in history
                if item.get("role") == "legacy_summary_unverified"
            )
        message_history = [
            item for item in history if item.get("role") != "legacy_summary_unverified"
        ]
        if message_history:
            lines.append("Older message excerpts (recent raw messages omitted):")
            lines.extend(
                f"- [{item['id']}] {item['role']}: {item['text']}" for item in message_history
            )
    lines.append(
        "Omitted items: "
        f"constraints={omitted_constraints}, pinned={omitted_pinned}, "
        f"approved={omitted_approved}, local={omitted_local}, "
        f"artifacts={omitted_artifacts}, citations={omitted_citations}, "
        f"history={omitted_history}."
    )
    return "\n".join(line for line in lines if line.strip())


def _render_history_summary(
    *,
    history: list[dict[str, Any]],
    boundary: CompactionBoundary,
    omitted_history: int,
) -> str:
    """Render only historical excerpts for callers that already render state fields."""
    lines = [
        "Context history snapshot:",
        (
            f"Coverage: source messages {boundary.prefix_end}/{len(boundary.source_messages)}; "
            f"recent raw messages kept separately ({len(boundary.recent_messages)} messages, "
            f"{boundary.recent_token_count} estimated tokens)."
        ),
    ]
    legacy = [item for item in history if item.get("role") == "legacy_summary_unverified"]
    if legacy:
        lines.append("Legacy summary excerpts (unparsed; not authoritative):")
        lines.extend(f"- [{item['id']}] {item['text']}" for item in legacy)
    messages = [item for item in history if item.get("role") != "legacy_summary_unverified"]
    if messages:
        lines.append("Older message excerpts (recent raw messages omitted):")
        lines.extend(f"- [{item['id']}] {item['role']}: {item['text']}" for item in messages)
    lines.append(f"Omitted history excerpts: {omitted_history}.")
    return "\n".join(lines)


def _omitted_counts(
    values: Mapping[str, Any], *, history: list[dict[str, Any]], omitted_history: int
) -> dict[str, int]:
    return {
        "history": omitted_history,
        **{
            key: max(0, len(list(values.get(key, []) or [])) - MAX_SECTION_ITEMS)
            for key in (
                "user_constraints",
                "pinned_facts",
                "imported_findings",
                "branch_local_findings",
                "artifacts",
                "citations",
            )
        },
    }


def _drift_report(values: Mapping[str, Any], summary: str) -> dict[str, Any]:
    recall_targets = [
        _text(values.get("active_goal")),
        *[
            _item_text(item, "constraint", "content")
            for item in list(values.get("user_constraints", []) or [])
        ],
        *[
            _item_text(item, "fact", "content")
            for item in list(values.get("pinned_facts", []) or [])
        ],
        *[_format_finding(item) for item in list(values.get("imported_findings", []) or [])],
        *[_format_finding(item) for item in list(values.get("branch_local_findings", []) or [])],
    ]
    grounding_targets = [
        *[_format_artifact(item) for item in list(values.get("artifacts", []) or [])],
        *[_format_artifact(item) for item in list(values.get("citations", []) or [])],
        *[
            ref
            for item in [
                *list(values.get("imported_findings", []) or []),
                *list(values.get("branch_local_findings", []) or []),
            ]
            for ref in _item_refs(item)
        ],
    ]
    answerability_targets = [_text(values.get("active_goal"))]
    answerability_targets.extend(
        _item_text(item, "constraint", "content")
        for item in list(values.get("user_constraints", []) or [])
    )
    source_text = "\n".join(
        [
            _text(values.get("active_goal")),
            *[
                _item_text(item, "constraint", "content")
                for item in list(values.get("user_constraints", []) or [])
            ],
            *[
                _item_text(item, "fact", "content")
                for item in list(values.get("pinned_facts", []) or [])
            ],
            *[_format_finding(item) for item in list(values.get("imported_findings", []) or [])],
            *[
                _format_finding(item)
                for item in list(values.get("branch_local_findings", []) or [])
            ],
            *[_format_artifact(item) for item in list(values.get("artifacts", []) or [])],
            *[_format_artifact(item) for item in list(values.get("citations", []) or [])],
        ]
    )
    recall = _coverage(recall_targets, summary)
    grounding = _coverage(grounding_targets, summary)
    answerability = _coverage(answerability_targets, summary)
    precision = _precision(summary, source_text)
    overall_drift = round(1.0 - ((recall + precision + grounding + answerability) / 4), 4)
    risk = "high" if overall_drift >= 0.34 else "medium" if overall_drift > 0 else "low"
    return {
        "recall": recall,
        "precision": precision,
        "grounding": grounding,
        "answerability": answerability,
        "overall_drift": overall_drift,
        "drift_risk": risk,
        "target_counts": {
            "recall": len(_dedupe(recall_targets)),
            "grounding": len(_dedupe(grounding_targets)),
            "answerability": len(_dedupe(answerability_targets)),
        },
        "method": "structural_lexical",
    }


def _dedupe(items: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = " ".join(str(item or "").split()).casefold()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _coverage(targets: Sequence[str], summary: str) -> float:
    normalized_summary = " ".join(summary.casefold().split())
    values = _dedupe(targets)
    if not values:
        return 1.0
    return round(sum(1 for target in values if target in normalized_summary) / len(values), 4)


def _precision(summary: str, source_text: str) -> float:
    source = " ".join(source_text.casefold().split())
    claims = [line.strip("- ").strip() for line in summary.splitlines() if line.startswith("-")]
    claims = [" ".join(claim.split()).casefold() for claim in claims if len(claim.strip()) >= 12]
    if not claims:
        return 1.0
    return round(sum(1 for claim in claims if claim in source) / len(claims), 4)


def _clip(value: Any, max_chars: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return f"{text[: max(0, max_chars - 15)].rstrip()} ...[trimmed]"


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


__all__ = [
    "COMPACTION_VERSION",
    "CompactionBoundary",
    "build_incremental_compaction_update",
    "compaction_message_boundary",
    "select_recent_messages",
]
