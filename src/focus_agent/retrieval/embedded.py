"""Shared embed -> search/upsert helpers for retrieval collections."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from .index import RetrievalDocument, RetrievalIndex, RetrievalSearchHit

EMBED_BATCH_SIZE = 64


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def embed_texts_batched(
    embedding_provider: Any,
    texts: Sequence[str],
    *,
    batch_size: int = EMBED_BATCH_SIZE,
) -> list[Sequence[float]]:
    vectors: list[Sequence[float]] = []
    for start in range(0, len(texts), batch_size):
        vectors.extend(embedding_provider.embed(list(texts[start : start + batch_size])))
    return vectors


def embedded_search(
    *,
    retrieval_index: RetrievalIndex | None,
    embedding_provider: Any | None,
    collection: str,
    query: str,
    limit: int,
    filters: Mapping[str, object] | None = None,
) -> list[RetrievalSearchHit]:
    if retrieval_index is None or embedding_provider is None:
        return []
    return retrieval_index.search(
        collection=collection,
        query=query,
        vector=embedding_provider.embed([query])[0],
        limit=limit,
        filters=filters,
    )


def upsert_embedded_document(
    *,
    retrieval_index: RetrievalIndex,
    embedding_provider: Any,
    collection: str,
    doc_id: str,
    source_id: str,
    text: str,
    fields: Mapping[str, object],
    vector: Sequence[float] | None = None,
) -> None:
    retrieval_index.upsert(
        RetrievalDocument(
            collection=collection,
            doc_id=doc_id,
            source_id=source_id,
            text=text,
            vector=vector if vector is not None else embedding_provider.embed([text])[0],
            fields={**fields, "content_hash": content_hash(text)},
        )
    )


__all__ = [
    "EMBED_BATCH_SIZE",
    "content_hash",
    "embed_texts_batched",
    "embedded_search",
    "upsert_embedded_document",
]
