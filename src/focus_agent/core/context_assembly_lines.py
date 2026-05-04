from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable


_LINE_SCORE_RE = re.compile(r"\[score\s+([0-9.]+)\]\s*$", re.IGNORECASE)


_LINE_CONFIDENCE_RE = re.compile(r"\(confidence\s+([0-9.]+)\)", re.IGNORECASE)


_LINE_EVIDENCE_RE = re.compile(r"\[evidence:\s*([^\]]+)\]", re.IGNORECASE)


_LINE_SOURCE_PREFIX_RE = re.compile(r"^\[[^\]]+\]\s*")


_ARTIFACT_URI_RE = re.compile(r"\(([^()\s]+)\)\s*$")


_ARTIFACT_LINE_RE = re.compile(
    r"^(?P<title>.+?)\s\[(?P<kind>[^\[\]]+)\](?:\s\((?P<uri>[^()]+)\))?$"
)


@dataclass(slots=True)
class _PromptFindingCandidate:
    line: str
    section: str
    dedupe_key: str
    confidence: float
    evidence_count: int
    recency_order: int
    promoted: bool


@dataclass(slots=True)
class _PromptMemoryCandidate:
    line: str
    dedupe_key: str
    promoted: bool
    confidence: float
    evidence_count: int
    score: float
    recency_order: int


@dataclass(slots=True)
class _PromptArtifactCandidate:
    line: str
    dedupe_key: str
    has_artifact_id: bool
    has_uri: bool
    has_summary: bool
    recency_order: int


@dataclass(slots=True)
class _PromptTextCandidate:
    line: str
    dedupe_key: str
    promoted: bool
    confidence: float
    evidence_count: int
    score: float
    has_uri: bool
    recency_order: int


def _text_candidate(line: str, *, recency_order: int) -> _PromptTextCandidate:
    stripped = line.strip()
    source_stripped = _LINE_SOURCE_PREFIX_RE.sub("", stripped)
    artifact_key = _artifact_dedupe_key(source_stripped)
    dedupe_key = (
        artifact_key
        or _normalize_for_dedupe(_strip_line_metadata(source_stripped))
        or _normalize_for_dedupe(stripped)
    )
    return _PromptTextCandidate(
        line=stripped,
        dedupe_key=dedupe_key or f"line:{recency_order}",
        promoted=_looks_promoted_line(stripped),
        confidence=_extract_line_confidence(stripped),
        evidence_count=_extract_line_evidence_count(stripped),
        score=_extract_line_score(stripped),
        has_uri=bool(_ARTIFACT_URI_RE.search(stripped)),
        recency_order=recency_order,
    )


def _text_candidate_preference(candidate: _PromptTextCandidate) -> tuple[float, ...]:
    return (
        1.0 if candidate.promoted else 0.0,
        candidate.confidence,
        float(candidate.evidence_count),
        candidate.score,
        1.0 if candidate.has_uri else 0.0,
        float(candidate.recency_order),
    )


def _strip_line_metadata(text: str) -> str:
    stripped = _LINE_SCORE_RE.sub("", text).strip()
    stripped = _LINE_EVIDENCE_RE.sub("", stripped).strip()
    stripped = _LINE_CONFIDENCE_RE.sub("", stripped).strip()
    return stripped


def _normalize_for_dedupe(text: str) -> str:
    lowered = str(text or "").casefold().strip()
    lowered = re.sub(r"[^0-9a-z\u4e00-\u9fff/._:-]+", " ", lowered)
    return " ".join(lowered.split())


def _looks_promoted_line(text: str) -> bool:
    lowered = text.casefold()
    return (
        "root_thread" in lowered
        or "imported_conclusion" in lowered
        or "approved finding" in lowered
        or "already approved" in lowered
    )


def _extract_line_confidence(text: str) -> float:
    match = _LINE_CONFIDENCE_RE.search(text)
    if not match:
        return 0.0
    try:
        return float(match.group(1))
    except ValueError:
        return 0.0


def _extract_line_evidence_count(text: str) -> int:
    match = _LINE_EVIDENCE_RE.search(text)
    if not match:
        return 0
    values = [item.strip() for item in match.group(1).split(",") if item.strip()]
    return len(values)


def _extract_line_score(text: str) -> float:
    match = _LINE_SCORE_RE.search(text)
    if not match:
        return 0.0
    try:
        return float(match.group(1))
    except ValueError:
        return 0.0


def _artifact_dedupe_key(text: str) -> str:
    match = _ARTIFACT_LINE_RE.match(text.strip())
    if match:
        kind = str(match.group("kind") or "").strip().casefold()
        if not kind.startswith(("evidence:", "score ")) and kind != "score":
            title = str(match.group("title") or "").strip()
            return _normalize_for_dedupe(f"{title} {kind}")
    return ""


def _semantic_line_key(line: str) -> str:
    normalized = _LINE_SOURCE_PREFIX_RE.sub("", str(line or "").strip())
    artifact_key = _artifact_dedupe_key(normalized)
    if artifact_key:
        return artifact_key
    normalized = _LINE_SCORE_RE.sub("", normalized)
    normalized = _LINE_EVIDENCE_RE.sub("", normalized)
    normalized = _LINE_CONFIDENCE_RE.sub("", normalized)
    normalized = re.sub(r"[^0-9a-z\u4e00-\u9fff/._:-]+", " ", normalized.casefold())
    return " ".join(normalized.split())


def _line_preference(line: str) -> tuple[float, ...]:
    lowered = line.casefold()
    evidence_match = _LINE_EVIDENCE_RE.search(line)
    evidence_count = 0
    if evidence_match:
        evidence_count = len(
            [item.strip() for item in evidence_match.group(1).split(",") if item.strip()]
        )
    return (
        1.0
        if "approved" in lowered
        or "主线" in lowered
        or "root_thread/imported_conclusion" in lowered
        else 0.0,
        _extract_numeric(_LINE_CONFIDENCE_RE, line),
        float(evidence_count),
        _extract_numeric(_LINE_SCORE_RE, line),
        1.0 if _ARTIFACT_URI_RE.search(line) else 0.0,
        float(len(line)),
    )


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
    return _dedupe_ranked_lines(
        lines, limit=limit, key_fn=_text_line_dedupe_key, rank_fn=lambda line: (len(line),)
    )


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


def _first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


__all__ = [
    "_ARTIFACT_LINE_RE",
    "_ARTIFACT_URI_RE",
    "_LINE_CONFIDENCE_RE",
    "_LINE_EVIDENCE_RE",
    "_LINE_SCORE_RE",
    "_LINE_SOURCE_PREFIX_RE",
    "_PromptArtifactCandidate",
    "_PromptFindingCandidate",
    "_PromptMemoryCandidate",
    "_PromptTextCandidate",
    "_artifact_dedupe_key",
    "_artifact_line_dedupe_key",
    "_artifact_line_rank",
    "_dedupe_artifact_lines",
    "_dedupe_finding_lines",
    "_dedupe_memory_lines",
    "_dedupe_preferring_reference",
    "_dedupe_ranked_lines",
    "_dedupe_text_lines",
    "_extract_line_confidence",
    "_extract_line_evidence_count",
    "_extract_line_score",
    "_extract_numeric",
    "_finding_line_dedupe_key",
    "_finding_line_rank",
    "_first_nonempty_line",
    "_line_preference",
    "_looks_promoted_line",
    "_memory_line_dedupe_key",
    "_memory_line_rank",
    "_normalize_for_dedupe",
    "_semantic_line_key",
    "_strip_line_metadata",
    "_text_candidate",
    "_text_candidate_preference",
    "_text_line_dedupe_key",
]
