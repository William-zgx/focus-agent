from __future__ import annotations

from typing import Any, Iterable

from .types import ArtifactRef, ConstraintItem, FindingItem, PinnedFact


def _coerce_pinned_facts(values: Iterable[Any]) -> list[PinnedFact]:
    facts: list[PinnedFact] = []
    for value in values:
        if isinstance(value, PinnedFact):
            facts.append(value)
        elif isinstance(value, dict):
            facts.append(PinnedFact.model_validate(value))
        elif value:
            facts.append(PinnedFact(fact=str(value)))
    return facts


def _coerce_constraints(values: Iterable[Any]) -> list[ConstraintItem]:
    constraints: list[ConstraintItem] = []
    for value in values:
        if isinstance(value, ConstraintItem):
            constraints.append(value)
        elif isinstance(value, dict):
            constraints.append(ConstraintItem.model_validate(value))
        elif value:
            constraints.append(ConstraintItem(constraint=str(value)))
    return constraints


def _coerce_local_finding_lines(values: Iterable[Any], *, limit: int) -> list[str]:
    findings: list[str] = []
    for value in values:
        finding = _finding_to_line(value)
        if finding:
            findings.append(finding)
    if limit <= 0:
        return []
    return findings


def _coerce_imported_lines(values: Iterable[Any]) -> list[str]:
    findings: list[str] = []
    for value in values:
        if isinstance(value, FindingItem):
            findings.append(_finding_to_line(value))
        elif isinstance(value, dict):
            findings.append(_finding_to_line(FindingItem.model_validate(value)))
        elif value:
            findings.append(str(value))
    return [line for line in findings if line]


def _coerce_legacy_imported_lines(values: Iterable[Any]) -> list[str]:
    lines: list[str] = []
    for value in values:
        if isinstance(value, dict):
            branch_label = value.get("branch_name") or value.get("branch_id") or "branch"
            summary = value.get("summary") or ""
            if summary:
                lines.append(f"[{branch_label}] {summary}")
        elif value:
            lines.append(str(value))
    return lines


def _coerce_artifact_lines(values: Iterable[Any], *, limit: int, include_local: bool) -> list[str]:
    if not include_local:
        return []

    lines: list[str] = []
    for value in values:
        if isinstance(value, ArtifactRef):
            lines.append(_artifact_to_line(value))
        elif isinstance(value, dict):
            lines.append(_artifact_to_line(ArtifactRef.model_validate(value)))
        elif value:
            lines.append(str(value))
    if limit <= 0:
        return []
    return [line for line in lines if line]


def _artifact_to_line(artifact: ArtifactRef) -> str:
    location = f" ({artifact.uri})" if artifact.uri else ""
    return f"{artifact.title} [{artifact.kind}]{location}"


def _finding_to_line(value: Any) -> str:
    if isinstance(value, FindingItem):
        confidence = "" if value.confidence is None else f" (confidence {value.confidence:.2f})"
        refs = "" if not value.evidence_refs else f" [evidence: {', '.join(value.evidence_refs)}]"
        return f"{value.finding}{confidence}{refs}"
    if isinstance(value, dict):
        return _finding_to_line(FindingItem.model_validate(value))
    return str(value)


__all__ = [
    "_artifact_to_line",
    "_coerce_artifact_lines",
    "_coerce_constraints",
    "_coerce_imported_lines",
    "_coerce_legacy_imported_lines",
    "_coerce_local_finding_lines",
    "_coerce_pinned_facts",
    "_finding_to_line",
]
