"""Render the structured compaction snapshot and score it for drift.

Split out of ``context_compaction`` so the cursor/boundary logic and the
summary text it produces can be read separately.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .context_compaction import CompactionBoundary

MAX_SECTION_ITEMS = 8
MAX_ITEM_CHARS = 320


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
