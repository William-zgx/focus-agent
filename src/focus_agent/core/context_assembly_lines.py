from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

_LINE_SCORE_RE = re.compile(r"\[score\s+([0-9.]+)\]\s*$", re.IGNORECASE)


_LINE_CONFIDENCE_RE = re.compile(r"\(confidence\s+([0-9.]+)\)", re.IGNORECASE)


_LINE_EVIDENCE_RE = re.compile(r"\[evidence:\s*([^\]]+)\]", re.IGNORECASE)


_LINE_SOURCE_PREFIX_RE = re.compile(r"^\[[^\]]+\]\s*")


_ARTIFACT_URI_RE = re.compile(r"\(([^()\s]+)\)\s*$")


def _dedupe_ranked_lines(lines: Iterable[str], *, limit: int, key_fn, rank_fn) -> list[str]:
    if limit <= 0:
        return []
    selected: dict[str, tuple[tuple[Any, ...], str]] = {}
    for recency_order, raw in enumerate(str(line).strip() for line in lines if str(line).strip()):
        key = key_fn(raw)
        rank = (*rank_fn(raw), recency_order)
        current = selected.get(key)
        if current is None or rank > current[0]:
            selected[key] = (rank, raw)
    ordered = sorted(selected.values(), key=lambda item: item[0], reverse=True)
    return [line for _, line in ordered[:limit]][::-1]


def _text_line_dedupe_key(line: str) -> str:
    return " ".join(str(line).split()).casefold()


def _finding_line_dedupe_key(line: str) -> str:
    normalized = _LINE_SOURCE_PREFIX_RE.sub("", str(line).strip())
    normalized = _LINE_EVIDENCE_RE.sub("", normalized)
    normalized = _LINE_CONFIDENCE_RE.sub("", normalized)
    normalized = _LINE_SCORE_RE.sub("", normalized)
    return _text_line_dedupe_key(normalized)


def _memory_line_dedupe_key(line: str) -> str:
    normalized = _LINE_SOURCE_PREFIX_RE.sub("", str(line).strip())
    normalized = _LINE_SCORE_RE.sub("", normalized)
    return _text_line_dedupe_key(normalized)


def _artifact_line_dedupe_key(line: str) -> str:
    normalized = _ARTIFACT_URI_RE.sub("", str(line).strip())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized.casefold()


def _finding_line_rank(line: str) -> tuple[int, float, int, int]:
    text = str(line)
    promoted = 1 if "approved" in text.casefold() or text.startswith("[root_thread") else 0
    confidence = _extract_numeric(_LINE_CONFIDENCE_RE, text)
    evidence_count = 0
    evidence_match = _LINE_EVIDENCE_RE.search(text)
    if evidence_match:
        evidence_count = len([item for item in evidence_match.group(1).split(",") if item.strip()])
    return promoted, confidence, evidence_count, len(text)


def _memory_line_rank(line: str) -> tuple[int, float, int]:
    text = str(line)
    promoted = 1 if "root_thread/imported_conclusion" in text else 0
    score = _extract_numeric(_LINE_SCORE_RE, text)
    return promoted, score, len(text)


def _artifact_line_rank(line: str) -> tuple[int, int, int]:
    text = str(line)
    has_uri = 1 if _ARTIFACT_URI_RE.search(text) else 0
    return has_uri, len(text), 0


def _extract_numeric(pattern: re.Pattern[str], text: str) -> float:
    match = pattern.search(text)
    if match is None:
        return 0.0
    try:
        return float(match.group(1))
    except (IndexError, ValueError):
        return 0.0


def _dedupe_text_lines(lines: Iterable[str], *, limit: int) -> list[str]:
    """Drop repeated lines, keeping chronological order and the newest ``limit`` entries."""
    if limit <= 0:
        return []
    selected: dict[str, str] = {}
    for raw in (str(line).strip() for line in lines):
        if raw:
            key = _text_line_dedupe_key(raw)
            selected.pop(key, None)
            selected[key] = raw
    return list(selected.values())[-limit:]


def _dedupe_finding_lines(lines: Iterable[str], *, limit: int) -> list[str]:
    return _dedupe_ranked_lines(
        lines, limit=limit, key_fn=_finding_line_dedupe_key, rank_fn=_finding_line_rank
    )


def _dedupe_memory_lines(lines: Iterable[str], *, limit: int) -> list[str]:
    return _dedupe_ranked_lines(
        lines, limit=limit, key_fn=_memory_line_dedupe_key, rank_fn=_memory_line_rank
    )


def _dedupe_artifact_lines(lines: Iterable[str], *, limit: int) -> list[str]:
    return _dedupe_ranked_lines(
        lines, limit=limit, key_fn=_artifact_line_dedupe_key, rank_fn=_artifact_line_rank
    )


def _dedupe_preferring_reference(
    reference_lines: Iterable[str], candidate_lines: Iterable[str], *, limit: int
) -> list[str]:
    if limit <= 0:
        return []
    reference_keys = {
        _finding_line_dedupe_key(line) for line in reference_lines if str(line).strip()
    }
    filtered = [
        str(line).strip()
        for line in candidate_lines
        if str(line).strip() and _finding_line_dedupe_key(str(line)) not in reference_keys
    ]
    return _dedupe_finding_lines(filtered, limit=limit)


__all__ = [
    "_ARTIFACT_URI_RE",
    "_LINE_CONFIDENCE_RE",
    "_LINE_EVIDENCE_RE",
    "_LINE_SCORE_RE",
    "_LINE_SOURCE_PREFIX_RE",
    "_artifact_line_dedupe_key",
    "_artifact_line_rank",
    "_dedupe_artifact_lines",
    "_dedupe_finding_lines",
    "_dedupe_memory_lines",
    "_dedupe_preferring_reference",
    "_dedupe_ranked_lines",
    "_dedupe_text_lines",
    "_extract_numeric",
    "_finding_line_dedupe_key",
    "_finding_line_rank",
    "_memory_line_dedupe_key",
    "_memory_line_rank",
    "_text_line_dedupe_key",
]
