"""Fork-time branch brief: what a child branch knows about its parent.

The brief is stored once in ``branch_meta["fork_brief"]`` when a branch is
forked and rendered into the child's system prompt as background. It never
changes the stored or UI-visible transcript.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from .branch_messages import (
    _CONFIRM_MARKERS,
    _DISMISS_MARKERS,
    _branch_action_handoff_texts,
    _compact,
    _is_ai_message_type,
    _is_branch_action_request,
    _is_copied_branch_control_ai_message,
    _is_human_message_type,
    _message_content,
    _message_content_to_text,
    _message_type_name,
    branch_fork_message_count,
    branch_visible_messages,
)

FORK_BRIEF_KEYS = (
    "goal",
    "parent_summary",
    "parent_recent_turns",
    "forked_at",
    "parent_message_count",
)
FORK_BRIEF_TURN_LIMIT = 3
FORK_BRIEF_TURN_MAX_CHARS = 800
FORK_BRIEF_SUMMARY_MAX_CHARS = 2000
FORK_BRIEF_GOAL_MAX_CHARS = 400
# Rendering caps keep the brief well inside the system prompt budget.
_RENDER_TURN_MAX_CHARS = 400
_RENDER_SUMMARY_MAX_CHARS = 800
_RENDER_MAX_CHARS = 2400


def _clip(text: str, max_chars: int) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max(0, max_chars - 1)].rstrip() + "…"


def message_visible_text(message: Any) -> str:
    return " ".join(_message_content_to_text(_message_content(message)).split())


def thread_summary_text(values: Mapping[str, Any]) -> str:
    """Return the compaction summary when present, else the rolling summary."""
    compaction = values.get("context_compaction") or {}
    if (
        isinstance(compaction, Mapping)
        and compaction.get("compaction_version") == 2
        and str(compaction.get("history_summary") or "").strip()
    ):
        return str(compaction["history_summary"]).strip()
    return str(values.get("rolling_summary") or "").strip()


def _is_branch_control_request(text: str) -> bool:
    # Exact-match markers only: substring dismissal heuristics would drop real
    # requests such as "from now on" ("no") from the parent background.
    compact = _compact(text)
    return (
        compact in _CONFIRM_MARKERS
        or compact in _DISMISS_MARKERS
        or _is_branch_action_request(text)
    )


def visible_dialogue_messages(messages: list[Any], *, values: Mapping[str, Any]) -> list[Any]:
    """User/assistant messages with visible text, minus branch-control chatter."""
    handoff_texts = _branch_action_handoff_texts(dict(values))
    visible: list[Any] = []
    for message in branch_visible_messages(list(messages), values=dict(values)):
        message_type = _message_type_name(message)
        if _is_human_message_type(message_type):
            text = message_visible_text(message)
            if _is_branch_control_request(text) or text in handoff_texts:
                continue
        elif _is_ai_message_type(message_type):
            if _is_copied_branch_control_ai_message(message):
                continue
        else:
            continue
        if message_visible_text(message):
            visible.append(message)
    return visible


def recent_dialogue_turns(
    messages: list[Any],
    *,
    values: Mapping[str, Any],
    turn_limit: int = FORK_BRIEF_TURN_LIMIT,
    max_chars: int = FORK_BRIEF_TURN_MAX_CHARS,
) -> list[dict[str, str]]:
    """Last ``turn_limit`` user turns with their final visible assistant reply."""
    turns: list[list[dict[str, str]]] = []
    for message in visible_dialogue_messages(messages, values=values):
        role = "user" if _is_human_message_type(_message_type_name(message)) else "assistant"
        entry = {"role": role, "content": _clip(message_visible_text(message), max_chars)}
        if role == "user" or not turns:
            turns.append([entry])
            continue
        current = turns[-1]
        if current[-1]["role"] == "assistant":
            current[-1] = entry
        else:
            current.append(entry)
    selected = turns[-turn_limit:] if turn_limit > 0 else []
    return [entry for turn in selected for entry in turn]


def pending_fork_handoff_goal(parent_values: Mapping[str, Any], *, parent_thread_id: str) -> str:
    """Handoff text of the newest pending fork action that targets this parent."""
    for item in reversed(list(parent_values.get("branch_actions") or [])):
        payload = item if isinstance(item, Mapping) else getattr(item, "__dict__", {})
        kind = str(payload.get("kind") or getattr(item, "kind", "") or "")
        if kind not in {"fork_child_branch", "fork_sibling_branch"}:
            continue
        status = str(payload.get("status") or getattr(item, "status", "") or "")
        target = str(payload.get("target_parent_thread_id") or "")
        if status != "pending" or (target and target != parent_thread_id):
            continue
        text = _clip(payload.get("handoff_message") or "", FORK_BRIEF_GOAL_MAX_CHARS)
        if text:
            return text
    return ""


def build_fork_brief(
    parent_values: Mapping[str, Any],
    *,
    goal: str = "",
    forked_at: str | None = None,
) -> dict[str, Any]:
    messages = list(parent_values.get("messages") or [])
    return {
        "goal": _clip(goal, FORK_BRIEF_GOAL_MAX_CHARS),
        "parent_summary": _clip(thread_summary_text(parent_values), FORK_BRIEF_SUMMARY_MAX_CHARS),
        "parent_recent_turns": recent_dialogue_turns(messages, values=parent_values),
        "forked_at": forked_at or datetime.now(UTC).isoformat(),
        "parent_message_count": len(messages),
    }


def first_local_user_text(values: Mapping[str, Any]) -> str:
    fork_count = branch_fork_message_count(dict(values))
    if fork_count is None:
        return ""
    messages = list(values.get("messages") or [])
    for message in messages[fork_count:]:
        if not _is_human_message_type(_message_type_name(message)):
            continue
        text = message_visible_text(message)
        if text and not _is_branch_control_request(text):
            return _clip(text, FORK_BRIEF_GOAL_MAX_CHARS)
    return ""


def resolve_fork_brief(values: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return the stored brief with ``goal`` filled from the first local user turn."""
    branch_meta = values.get("branch_meta")
    if not isinstance(branch_meta, Mapping):
        return None
    brief = branch_meta.get("fork_brief")
    if not isinstance(brief, Mapping):
        return None
    resolved = dict(brief)
    if not str(resolved.get("goal") or "").strip():
        resolved["goal"] = first_local_user_text(values)
    return resolved


def fork_brief_goal_update(values: Mapping[str, Any]) -> dict[str, Any]:
    """State update that pins a newly derived goal; empty when nothing changes."""
    branch_meta = values.get("branch_meta")
    if not isinstance(branch_meta, Mapping):
        return {}
    stored = branch_meta.get("fork_brief")
    resolved = resolve_fork_brief(values)
    if not isinstance(stored, Mapping) or resolved is None:
        return {}
    goal = str(resolved.get("goal") or "")
    if not goal or goal == str(stored.get("goal") or ""):
        return {}
    update: dict[str, Any] = {"branch_meta": {**dict(branch_meta), "fork_brief": resolved}}
    if not str(values.get("active_goal") or "").strip():
        update["active_goal"] = goal
    return update


def render_branch_brief(brief: Mapping[str, Any] | None) -> str:
    if not isinstance(brief, Mapping):
        return ""
    goal = _clip(brief.get("goal") or "", FORK_BRIEF_GOAL_MAX_CHARS)
    summary = _clip(brief.get("parent_summary") or "", _RENDER_SUMMARY_MAX_CHARS)
    turns = [
        item
        for item in list(brief.get("parent_recent_turns") or [])
        if isinstance(item, Mapping) and str(item.get("content") or "").strip()
    ]
    head: list[str] = ["## Branch brief"]
    if goal:
        head.append(f"- Branch goal: {goal}")
    last_parent_request = next(
        (item for item in reversed(turns) if item.get("role") == "user"),
        None,
    )
    if last_parent_request is not None:
        head.append(
            "- Parent was working on: "
            + _clip(last_parent_request.get("content") or "", _RENDER_TURN_MAX_CHARS)
        )
    if summary:
        head.append(f"- Parent summary: {summary}")
    turn_lines = [
        f"- Parent {item.get('role') or 'user'} (background): "
        + _clip(item.get("content") or "", _RENDER_TURN_MAX_CHARS)
        for item in turns
    ]
    if len(head) == 1 and not turn_lines:
        return ""
    note = (
        "- Parent turns below are background from before the fork, not new requests; "
        "parent constraints still apply unless this branch revises them."
    )
    lines = [*head, note, *turn_lines] if turn_lines else head
    while turn_lines and len("\n".join(lines)) > _RENDER_MAX_CHARS:
        turn_lines = turn_lines[1:]
        lines = [*head, note, *turn_lines] if turn_lines else head
    return "\n".join(lines)


__all__ = [
    "FORK_BRIEF_KEYS",
    "build_fork_brief",
    "first_local_user_text",
    "fork_brief_goal_update",
    "message_visible_text",
    "pending_fork_handoff_goal",
    "recent_dialogue_turns",
    "render_branch_brief",
    "resolve_fork_brief",
    "thread_summary_text",
    "visible_dialogue_messages",
]
