"""Merge-time conflict detection across independent agent task outputs."""

from __future__ import annotations

import itertools
from typing import Any
from uuid import uuid5, NAMESPACE_URL

from .contracts import ConflictReport

_NEGATIVE_MARKERS = ("not ", "no ", "never ", "cannot ", "can't ", "won't ", "without ")
_POSITIVE_MARKERS = (" should ", " must ", " can ", " will ", " is ", " are ")


class MergeConflictDetector:
    """Heuristic detector for file overlap and contradictory task conclusions."""

    def detect(self, task_outputs: dict[str, dict[str, Any]]) -> list[ConflictReport]:
        reports: list[ConflictReport] = []
        for task_a, task_b in itertools.combinations(sorted(task_outputs), 2):
            output_a = task_outputs[task_a]
            output_b = task_outputs[task_b]
            shared_files = sorted(
                set(_as_strings(output_a.get("changed_files")))
                & set(_as_strings(output_b.get("changed_files")))
            )
            if shared_files:
                reports.append(
                    _report(
                        task_a=task_a,
                        task_b=task_b,
                        conflict_type="changed_files_overlap",
                        severity="blocking",
                        description=f"Tasks changed the same files: {', '.join(shared_files)}",
                        suggested_resolution="Review overlapping patches before building the merge bundle.",
                    )
                )
            if _summaries_conflict(str(output_a.get("summary") or ""), str(output_b.get("summary") or "")):
                reports.append(
                    _report(
                        task_a=task_a,
                        task_b=task_b,
                        conflict_type="conclusion_contradiction",
                        severity="warning",
                        description="Task summaries appear to make contradictory claims.",
                        suggested_resolution="Ask a reviewer to reconcile the task conclusions.",
                    )
                )
        return reports


def _as_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _summaries_conflict(left: str, right: str) -> bool:
    left_norm = f" {left.lower()} "
    right_norm = f" {right.lower()} "
    left_negative = any(marker in left_norm for marker in _NEGATIVE_MARKERS)
    right_negative = any(marker in right_norm for marker in _NEGATIVE_MARKERS)
    left_positive = any(marker in left_norm for marker in _POSITIVE_MARKERS)
    right_positive = any(marker in right_norm for marker in _POSITIVE_MARKERS)
    shared_terms = set(_keywords(left_norm)) & set(_keywords(right_norm))
    return bool(shared_terms and left_negative != right_negative and (left_positive or right_positive))


def _keywords(text: str) -> list[str]:
    stopwords = {"the", "and", "that", "with", "this", "task", "agent", "should", "must"}
    return [
        word.strip(".,:;()[]{}'\"")
        for word in text.split()
        if len(word.strip(".,:;()[]{}'\"")) >= 4 and word not in stopwords
    ]


def _report(
    *,
    task_a: str,
    task_b: str,
    conflict_type: str,
    severity: str,
    description: str,
    suggested_resolution: str,
) -> ConflictReport:
    conflict_id = uuid5(NAMESPACE_URL, "|".join([task_a, task_b, conflict_type])).hex
    return ConflictReport(
        conflict_id=conflict_id,
        task_a=task_a,
        task_b=task_b,
        conflict_type=conflict_type,
        severity=severity,
        description=description,
        suggested_resolution=suggested_resolution,
    )


__all__ = ["MergeConflictDetector"]
