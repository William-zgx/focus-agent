"""Approved branch conclusions rendered from ``merge_queue`` for prompt assembly.

``merge_queue`` lives in thread state, so this block survives rolling-summary
compaction of the parent thread. It has its own budget, separate from the
generic findings lines.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .message_utils import clip_text

APPROVED_CONCLUSIONS_TITLE = "Approved branch conclusions"
APPROVED_CONCLUSIONS_MAX_ENTRIES = 6
APPROVED_CONCLUSIONS_MAX_CHARS = 3600
_SUMMARY_MAX_CHARS = 400
_ITEM_MAX_CHARS = 240
_FINDINGS_PER_ENTRY = 6
_QUESTIONS_PER_ENTRY = 3
_ARTIFACTS_PER_ENTRY = 4


def _strings(values: Any, *, limit: int) -> list[str]:
    items = [str(item).strip() for item in values or [] if str(item or "").strip()]
    return items[:limit]


def approved_conclusion_entries(merge_queue: Iterable[Any]) -> list[dict[str, Any]]:
    """Merge-queue entries with an approved summary, newest first."""
    entries = [
        dict(item)
        for item in merge_queue or []
        if isinstance(item, Mapping) and str(item.get("summary") or "").strip()
    ]
    return list(reversed(entries))


def _entry_lines(entry: Mapping[str, Any]) -> list[str]:
    label = clip_text(entry.get("branch_name") or entry.get("branch_id") or "branch", 60)
    imported_at = str(entry.get("imported_at") or "")[:10]
    tag = f"[{label} · {imported_at}]" if imported_at else f"[{label}]"
    refs = _strings(entry.get("evidence_refs"), limit=6)
    finding_refs = entry.get("finding_evidence_refs")
    lines = [f"{tag} {clip_text(entry.get('summary'), _SUMMARY_MAX_CHARS)}"]
    for finding in _strings(entry.get("key_findings"), limit=_FINDINGS_PER_ENTRY):
        own = finding_refs.get(finding) if isinstance(finding_refs, Mapping) else None
        cited = _strings(own if own is not None else refs, limit=4)
        suffix = f" [evidence: {', '.join(cited)}]" if cited else ""
        lines.append(f"{tag} finding: {clip_text(finding, _ITEM_MAX_CHARS)}{suffix}")
    for question in _strings(entry.get("open_questions"), limit=_QUESTIONS_PER_ENTRY):
        lines.append(f"{tag} open question: {clip_text(question, _ITEM_MAX_CHARS)}")
    artifacts = _strings(entry.get("artifacts"), limit=_ARTIFACTS_PER_ENTRY)
    if artifacts:
        lines.append(f"{tag} artifacts: {clip_text(', '.join(artifacts), _ITEM_MAX_CHARS)}")
    return lines


def render_approved_conclusions(
    merge_queue: Iterable[Any],
    *,
    max_entries: int = APPROVED_CONCLUSIONS_MAX_ENTRIES,
    max_chars: int = APPROVED_CONCLUSIONS_MAX_CHARS,
) -> tuple[str, list[dict[str, Any]]]:
    """Return the rendered block and the entries it represents (newest first)."""
    rendered: list[dict[str, Any]] = []
    lines: list[str] = []
    used = len(APPROVED_CONCLUSIONS_TITLE) + 4
    for entry in approved_conclusion_entries(merge_queue)[: max(0, max_entries)]:
        entry_lines = _entry_lines(entry)
        cost = sum(len(line) + 3 for line in entry_lines)
        if rendered and used + cost > max_chars:
            break
        rendered.append(entry)
        lines.extend(entry_lines)
        used += cost
    if not lines:
        return "", []
    block = f"## {APPROVED_CONCLUSIONS_TITLE}\n" + "\n".join(f"- {line}" for line in lines)
    return block, rendered


__all__ = [
    "APPROVED_CONCLUSIONS_TITLE",
    "approved_conclusion_entries",
    "render_approved_conclusions",
]
