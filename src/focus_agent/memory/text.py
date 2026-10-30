"""Shared text heuristics for memory write, dedupe, and retrieval paths."""

from __future__ import annotations

import re

_LATIN_TOKEN_PATTERNS = {
    2: re.compile(r"[a-z0-9]{2,}"),
    3: re.compile(r"[a-z0-9]{3,}"),
}
_CJK_SEQUENCE_PATTERN = re.compile(r"[一-鿿]+")
_DEDUPE_NOISE_PATTERN = re.compile(r"[^0-9a-z一-鿿/._:-]+")
_CORRECTION_MARKERS = (
    "纠正",
    "更正",
    "修正",
    "改成",
    "改为",
    "更新为",
    "以此为准",
    "以这个为准",
    "instead",
    "from now on",
    "correction",
    "corrected",
)


def normalize_memory_text(text: str | None) -> str:
    """Casefold and collapse whitespace for equality checks."""

    return " ".join((text or "").casefold().split())


def normalize_memory_dedupe_text(text: str | None) -> str:
    """Casefold and drop punctuation noise so near-identical lines compare equal."""

    lowered = _DEDUPE_NOISE_PATTERN.sub(" ", (text or "").casefold())
    return " ".join(lowered.split())


def memory_text_terms(text: str | None, *, min_latin_length: int = 2) -> list[str]:
    """Ordered unique Latin word tokens plus CJK bigrams (short CJK runs kept whole)."""

    raw = str(text or "")
    terms: list[str] = []
    seen: set[str] = set()

    def _add(term: str) -> None:
        if term and term not in seen:
            seen.add(term)
            terms.append(term)

    for token in _LATIN_TOKEN_PATTERNS[min_latin_length].findall(raw.casefold()):
        _add(token)
    for sequence in _CJK_SEQUENCE_PATTERN.findall(raw):
        compact = "".join(sequence.split())
        if len(compact) <= 2:
            _add(compact)
            continue
        for index in range(len(compact) - 1):
            _add(compact[index : index + 2])
    return terms


def has_correction_signal(text: str | None) -> bool:
    raw = text or ""
    lowered = raw.casefold()
    if any(marker in lowered for marker in _CORRECTION_MARKERS):
        return True
    # "不是…改为" / "不再…改为" are already covered by the "改为" marker.
    return "不是" in raw and "而是" in raw


__all__ = [
    "has_correction_signal",
    "memory_text_terms",
    "normalize_memory_dedupe_text",
    "normalize_memory_text",
]
