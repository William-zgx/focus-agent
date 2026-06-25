from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RetrievalDocument:
    collection: str
    doc_id: str
    source_id: str
    text: str
    fields: Mapping[str, object] = field(default_factory=dict)
    vector: Sequence[float] | None = None


@dataclass(frozen=True, slots=True)
class RetrievalSearchHit:
    doc_id: str
    source_id: str
    score: float
    text: str = ""
    fields: Mapping[str, object] = field(default_factory=dict)


class RetrievalIndex(Protocol):
    def upsert(self, document: RetrievalDocument) -> None: ...

    def delete(self, *, collection: str, doc_id: str) -> None: ...

    def search(
        self,
        *,
        collection: str,
        query: str,
        limit: int,
        vector: Sequence[float] | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> list[RetrievalSearchHit]: ...

    def stats(self) -> dict[str, object]: ...


class InMemoryRetrievalIndex:
    def __init__(self) -> None:
        self._docs: dict[tuple[str, str], RetrievalDocument] = {}

    def upsert(self, document: RetrievalDocument) -> None:
        self._docs[(document.collection, document.doc_id)] = document

    def delete(self, *, collection: str, doc_id: str) -> None:
        self._docs.pop((collection, doc_id), None)

    def search(
        self,
        *,
        collection: str,
        query: str,
        limit: int,
        vector: Sequence[float] | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> list[RetrievalSearchHit]:
        scored: list[RetrievalSearchHit] = []
        query_terms = _terms(query)
        for (doc_collection, _), document in self._docs.items():
            if doc_collection != collection or not _matches_filters(document.fields, filters):
                continue
            score = _text_score(query_terms, document.text)
            if vector is not None and document.vector is not None:
                score += _cosine(vector, document.vector)
            if score <= 0:
                continue
            scored.append(
                RetrievalSearchHit(
                    doc_id=document.doc_id,
                    source_id=document.source_id,
                    score=round(score, 6),
                    text=document.text,
                    fields=dict(document.fields),
                )
            )
        scored.sort(key=lambda item: (-item.score, item.doc_id))
        return scored[: max(0, int(limit or 0))]

    def stats(self) -> dict[str, object]:
        counts: dict[str, int] = {}
        for collection, _ in self._docs:
            counts[collection] = counts.get(collection, 0) + 1
        return {"backend": "memory", "collections": counts, "documents": len(self._docs)}


def _matches_filters(
    fields: Mapping[str, object],
    filters: Mapping[str, object] | None,
) -> bool:
    for key, expected in dict(filters or {}).items():
        actual = fields.get(key)
        if isinstance(actual, (list, tuple)):
            actual = tuple(str(item) for item in actual)
        if isinstance(expected, (list, tuple)):
            expected = tuple(str(item) for item in expected)
        if actual != expected:
            return False
    return True


def _terms(value: str) -> tuple[str, ...]:
    terms = re.findall(r"[a-z0-9]{2,}|[\u3400-\u4dbf\u4e00-\u9fff]{1,}", value.lower())
    return tuple(dict.fromkeys(terms))


def _text_score(query_terms: tuple[str, ...], text: str) -> float:
    if not query_terms:
        return 0.0
    haystack = text.lower()
    matched = sum(1 for term in query_terms if term in haystack)
    return matched / max(1, len(query_terms))


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(float(a) * float(b) for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(float(value) * float(value) for value in left))
    right_norm = math.sqrt(sum(float(value) * float(value) for value in right))
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return dot / (left_norm * right_norm)
