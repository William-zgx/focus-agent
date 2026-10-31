"""Branch-local inputs for the merge-review proposal prompt.

Everything here slices state at the fork boundary so the proposal sees what the
branch itself produced (messages, citations, artifacts, nested imports) rather
than whatever the thread happened to inherit from its parent.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .branch_brief import message_visible_text, thread_summary_text
from .branch_messages import (
    _is_ai_message_type,
    _is_human_message_type,
    _message_type_name,
    branch_fork_message_count,
    branch_visible_messages,
)

# State lists inherited at fork; their fork-time lengths are stored in
# ``branch_meta["fork_inherited_counts"]`` so later entries are branch-owned.
FORK_COUNTED_KEYS = (
    "imported_findings",
    "merge_queue",
    "branch_local_findings",
    "citations",
    "artifacts",
)
TRANSCRIPT_HEAD_MESSAGES = 4
TRANSCRIPT_TAIL_MESSAGES = 12
TRANSCRIPT_MESSAGE_MAX_CHARS = 600
TRANSCRIPT_MIDDLE_MAX_CHARS = 140
TRANSCRIPT_MIDDLE_LIMIT = 12
_LIST_LIMIT = 12


def clip_text(value: Any, max_chars: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 1)].rstrip() + "…"


def fork_inherited_counts_for(values: Mapping[str, Any]) -> dict[str, int]:
    return {key: len(list(values.get(key) or [])) for key in FORK_COUNTED_KEYS}


def _fork_counts(values: Mapping[str, Any]) -> dict[str, int] | None:
    branch_meta = values.get("branch_meta")
    if not isinstance(branch_meta, Mapping):
        return None
    counts = branch_meta.get("fork_inherited_counts")
    if not isinstance(counts, Mapping):
        return None
    parsed: dict[str, int] = {}
    for key in FORK_COUNTED_KEYS:
        try:
            parsed[key] = max(0, int(counts.get(key) or 0))
        except (TypeError, ValueError):
            parsed[key] = 0
    return parsed


def has_fork_boundary(values: Mapping[str, Any]) -> bool:
    return branch_fork_message_count(dict(values)) is not None or _fork_counts(values) is not None


def split_at_fork(values: Mapping[str, Any], key: str) -> tuple[list[Any], list[Any]]:
    """Return ``(inherited, branch_owned)`` items for a fork-counted state list.

    Branches without fork counts (legacy forks) treat everything as inherited
    for imports, and as branch-owned for the branch's own evidence lists.
    """
    items = list(values.get(key) or [])
    counts = _fork_counts(values)
    if counts is None:
        if key in {"imported_findings", "merge_queue"}:
            return items, []
        return [], items
    boundary = min(counts.get(key, 0), len(items))
    return items[:boundary], items[boundary:]


def branch_local_messages(values: Mapping[str, Any]) -> list[Any]:
    messages = list(values.get("messages") or [])
    fork_count = branch_fork_message_count(dict(values))
    if fork_count is not None and fork_count <= len(messages):
        candidates = branch_visible_messages(messages[fork_count:], values={})
    else:
        candidates = branch_visible_messages(messages, values=dict(values))
    local: list[Any] = []
    for message in candidates:
        message_type = _message_type_name(message)
        if not (_is_human_message_type(message_type) or _is_ai_message_type(message_type)):
            continue
        if message_visible_text(message):
            local.append(message)
    return local


def _role(message: Any) -> str:
    return "user" if _is_human_message_type(_message_type_name(message)) else "assistant"


def render_transcript(messages: list[Any]) -> str:
    """Keep the opening and closing turns whole; condense the middle."""
    head_count = TRANSCRIPT_HEAD_MESSAGES
    tail_count = TRANSCRIPT_TAIL_MESSAGES

    def full(message: Any) -> str:
        return f"{_role(message)}: " + clip_text(
            message_visible_text(message), TRANSCRIPT_MESSAGE_MAX_CHARS
        )

    if len(messages) <= head_count + tail_count:
        return "\n".join(full(message) for message in messages)
    head = messages[:head_count]
    middle = messages[head_count:-tail_count]
    tail = messages[-tail_count:]
    lines = [full(message) for message in head]
    lines.append(f"[{len(middle)} middle messages condensed]")
    for message in middle[:TRANSCRIPT_MIDDLE_LIMIT]:
        lines.append(
            f"  {_role(message)}: "
            + clip_text(message_visible_text(message), TRANSCRIPT_MIDDLE_MAX_CHARS)
        )
    if len(middle) > TRANSCRIPT_MIDDLE_LIMIT:
        lines.append(f"  [{len(middle) - TRANSCRIPT_MIDDLE_LIMIT} more omitted]")
    lines.extend(full(message) for message in tail)
    return "\n".join(lines)


def _payload(item: Any) -> dict[str, Any]:
    if isinstance(item, Mapping):
        return dict(item)
    if hasattr(item, "model_dump"):
        return item.model_dump(mode="json")
    return {}


def citation_lines(values: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []
    for item in split_at_fork(values, "citations")[1][-_LIST_LIMIT:]:
        payload = _payload(item)
        label = clip_text(payload.get("label") or payload.get("title") or "", 120)
        uri = clip_text(payload.get("uri") or payload.get("url") or "", 200)
        if label or uri:
            lines.append(f"{label} ({uri})" if label and uri else label or uri)
    return lines


def evidence_ledger_lines(values: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []
    for item in list(values.get("evidence_ledger") or [])[:_LIST_LIMIT]:
        payload = _payload(item)
        evidence_id = str(payload.get("id") or "").strip()
        title = clip_text(payload.get("title") or payload.get("source_name") or "", 120)
        url = clip_text(payload.get("url") or "", 200)
        parts = [part for part in (title, f"({url})" if url else "") if part]
        if evidence_id or parts:
            lines.append(f"{evidence_id}: {' '.join(parts)}".strip(": "))
    return lines


def artifact_lines(values: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []
    for item in split_at_fork(values, "artifacts")[1][-_LIST_LIMIT:]:
        payload = _payload(item)
        if not payload:
            text = clip_text(item, 160)
            if text:
                lines.append(text)
            continue
        title = clip_text(payload.get("title") or payload.get("artifact_id") or "", 120)
        uri = clip_text(payload.get("uri") or "", 200)
        if title:
            lines.append(f"{title} ({uri})" if uri else title)
    return lines


def branch_summary(values: Mapping[str, Any]) -> str:
    # The summary is reset at fork, so it is branch-local only past a fork boundary.
    if not has_fork_boundary(values):
        return ""
    return clip_text(thread_summary_text(values), 1200)


def finding_text(item: Any) -> str:
    if hasattr(item, "finding"):
        return str(item.finding or "").strip()
    if isinstance(item, Mapping):
        return str(item.get("finding") or "").strip()
    return str(item or "").strip()


def finding_refs(item: Any) -> list[str]:
    payload = _payload(item)
    return [str(ref).strip() for ref in payload.get("evidence_refs") or [] if str(ref).strip()]


def received_import_entries(values: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Imports applied to this branch after the fork (from its own child branches)."""
    entries: list[dict[str, Any]] = []
    for item in split_at_fork(values, "merge_queue")[1]:
        payload = _payload(item)
        if payload.get("summary") or payload.get("key_findings"):
            entries.append(payload)
    return entries


def received_import_findings(values: Mapping[str, Any]) -> list[Any]:
    return [item for item in split_at_fork(values, "imported_findings")[1] if finding_text(item)]


def render_received_imports(values: Mapping[str, Any]) -> str:
    lines: list[str] = []
    for entry in received_import_entries(values)[-6:]:
        name = clip_text(entry.get("branch_name") or entry.get("branch_id") or "branch", 60)
        lines.append(f"- [{name}] {clip_text(entry.get('summary') or '', 400)}")
        for finding in list(entry.get("key_findings") or [])[:6]:
            lines.append(f"  - {clip_text(finding, 300)}")
        for question in list(entry.get("open_questions") or [])[:3]:
            lines.append(f"  - Open question: {clip_text(question, 200)}")
    seen = {
        " ".join(str(finding).split())
        for entry in received_import_entries(values)
        for finding in entry.get("key_findings") or []
    }
    for item in received_import_findings(values)[-8:]:
        text = finding_text(item)
        if " ".join(text.split()) in seen:
            continue
        refs = finding_refs(item)
        suffix = f" [evidence: {', '.join(refs)}]" if refs else ""
        lines.append(f"- {clip_text(text, 300)}{suffix}")
    return "\n".join(lines) or "(none)"


UPSTREAM_STATE_KEY = "_merge_review_upstream"


def render_parent_updates(values: Mapping[str, Any]) -> str:
    """New parent turns and sibling imports since the fork (set during proposal prep)."""
    upstream = values.get(UPSTREAM_STATE_KEY)
    if not isinstance(upstream, Mapping) or not upstream.get("parent_moved_on"):
        return "(none)"
    lines: list[str] = []
    for turn in upstream.get("new_parent_turns") or []:
        if isinstance(turn, Mapping) and turn.get("content"):
            lines.append(
                f"- Parent {turn.get('role') or 'user'}: {clip_text(turn['content'], 400)}"
            )
    for entry in upstream.get("sibling_imports") or []:
        if not isinstance(entry, Mapping):
            continue
        name = clip_text(entry.get("branch_name") or entry.get("branch_id") or "branch", 60)
        lines.append(f"- Sibling import [{name}]: {clip_text(entry.get('summary') or '', 400)}")
        for finding in list(entry.get("key_findings") or [])[:6]:
            lines.append(f"  - {clip_text(finding, 300)}")
    return "\n".join(lines) or "- The parent thread changed since this branch forked."


def branch_owned_findings(values: Mapping[str, Any]) -> list[Any]:
    return [
        item for item in split_at_fork(values, "branch_local_findings")[1] if finding_text(item)
    ]


def known_evidence_refs(values: Mapping[str, Any]) -> set[str]:
    known: set[str] = set()
    for item in list(values.get("citations") or []):
        payload = _payload(item)
        known.update(
            str(payload.get(key) or "").strip() for key in ("label", "uri", "title", "url")
        )
    for item in list(values.get("evidence_ledger") or []):
        payload = _payload(item)
        known.update(str(payload.get(key) or "").strip() for key in ("id", "url", "title"))
    for item in [*branch_owned_findings(values), *received_import_findings(values)]:
        known.update(finding_refs(item))
    for entry in received_import_entries(values):
        known.update(str(ref).strip() for ref in entry.get("evidence_refs") or [])
    known.discard("")
    return known


def filter_known_refs(refs: Iterable[Any], known: set[str]) -> list[str]:
    """Keep refs matching a known citation/evidence entry (exact or by URL)."""
    folded = {item.casefold(): item for item in known}
    urls = [item for item in known if "://" in item]
    kept: list[str] = []
    for raw in refs:
        ref = str(raw or "").strip()
        if not ref:
            continue
        match = folded.get(ref.casefold())
        if match is None and any(url in ref for url in urls):
            match = ref
        if match is not None and match not in kept:
            kept.append(match)
    return kept


__all__ = [
    "FORK_COUNTED_KEYS",
    "artifact_lines",
    "branch_local_messages",
    "branch_owned_findings",
    "branch_summary",
    "citation_lines",
    "clip_text",
    "evidence_ledger_lines",
    "filter_known_refs",
    "finding_refs",
    "finding_text",
    "fork_inherited_counts_for",
    "has_fork_boundary",
    "known_evidence_refs",
    "received_import_entries",
    "received_import_findings",
    "UPSTREAM_STATE_KEY",
    "render_parent_updates",
    "render_received_imports",
    "render_transcript",
    "split_at_fork",
]
