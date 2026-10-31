"""Parent drift and sibling-conflict checks for merge proposal prep."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from ...core.branch_brief import message_visible_text, visible_dialogue_messages
from ...core.branch_messages import _is_human_message_type, _message_type_name
from ...core.branching import MergeConflict, MergeProposal
from ...core.merge_review_inputs import clip_text, split_at_fork
from ...memory.dedupe import has_textual_overlap
from ...memory.text import normalize_memory_dedupe_text

_NEW_TURN_LIMIT = 6
_SIBLING_IMPORT_LIMIT = 6
_WORD_RE = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?|[一-鿿]")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_NEGATIONS = {
    "not",
    "no",
    "never",
    "lack",
    "lacks",
    "without",
    "cannot",
    "isn",
    "doesn",
    "don",
    "won",
    "fails",
    "fail",
    "unsupported",
}
_CJK_NEGATIONS = ("不", "没", "无", "未", "非")


def upstream_changes(
    *,
    branch_id: str,
    child_values: Mapping[str, Any],
    parent_values: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """What the parent gained since the fork: new turns and sibling imports."""
    branch_meta = child_values.get("branch_meta")
    brief = branch_meta.get("fork_brief") if isinstance(branch_meta, Mapping) else None
    if not isinstance(brief, Mapping) or parent_values is None:
        return {"parent_moved_on": False, "new_parent_turns": [], "sibling_imports": []}
    try:
        forked_count = max(0, int(brief.get("parent_message_count") or 0))
    except (TypeError, ValueError):
        forked_count = 0
    parent_messages = list(parent_values.get("messages") or [])
    new_messages = parent_messages[forked_count:]
    new_turns = [
        {
            "role": "user" if _is_human_message_type(_message_type_name(message)) else "assistant",
            "content": clip_text(message_visible_text(message), 400),
        }
        for message in visible_dialogue_messages(new_messages, values={})
    ][-_NEW_TURN_LIMIT:]
    # Parent merge_queue entries past the child's fork-time count are sibling imports.
    inherited_count = len(split_at_fork(child_values, "merge_queue")[0])
    sibling_imports = [
        dict(item)
        for item in list(parent_values.get("merge_queue") or [])[inherited_count:]
        if isinstance(item, Mapping) and str(item.get("branch_id") or "") != branch_id
    ][-_SIBLING_IMPORT_LIMIT:]
    return {
        "parent_moved_on": len(parent_messages) > forked_count or bool(sibling_imports),
        "new_parent_turns": new_turns,
        "sibling_imports": sibling_imports,
    }


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(str(text or "").casefold())


def _negated(text: str) -> bool:
    words = set(_words(text))
    return bool(words & _NEGATIONS) or any(marker in str(text) for marker in _CJK_NEGATIONS)


def _aligned_substitution(left: list[str], right: list[str]) -> bool:
    if len(left) != len(right) or len(left) < 3:
        return False
    differing = sum(1 for a, b in zip(left, right, strict=True) if a != b)
    return 1 <= differing <= 2


def findings_conflict(left: str, right: str) -> bool:
    """Lexical check: same subject, contradicting value."""
    if normalize_memory_dedupe_text(left) == normalize_memory_dedupe_text(right):
        return False
    if not has_textual_overlap(left, right):
        return False
    if _negated(left) != _negated(right):
        return True
    left_numbers = set(_NUMBER_RE.findall(left))
    right_numbers = set(_NUMBER_RE.findall(right))
    if left_numbers and right_numbers and left_numbers != right_numbers:
        return True
    return _aligned_substitution(_words(left), _words(right))


def _claims(summary: Any, findings: Iterable[Any]) -> list[str]:
    claims = [str(item).strip() for item in findings or [] if str(item or "").strip()]
    if str(summary or "").strip():
        claims.append(str(summary).strip())
    return claims


def sibling_conflicts(
    proposal: MergeProposal, sibling_imports: Iterable[Mapping[str, Any]]
) -> list[MergeConflict]:
    conflicts: list[MergeConflict] = []
    seen: set[tuple[str, str]] = set()
    for finding in _claims(proposal.summary, proposal.key_findings):
        for entry in sibling_imports:
            branch_name = str(entry.get("branch_name") or entry.get("branch_id") or "branch")
            for other in _claims(entry.get("summary"), entry.get("key_findings") or []):
                if (finding, other) in seen or not findings_conflict(finding, other):
                    continue
                seen.add((finding, other))
                conflicts.append(
                    MergeConflict(
                        branch_name=branch_name, finding=finding, conflicting_finding=other
                    )
                )
    return conflicts


__all__ = ["findings_conflict", "sibling_conflicts", "upstream_changes"]
