from __future__ import annotations

import hashlib
from typing import Any

from .embedded import embed_texts_batched, upsert_embedded_document
from .index import RetrievalIndex


def index_artifact_content(
    *,
    retrieval_index: RetrievalIndex | None,
    embedding_provider: Any | None,
    artifact_id: str,
    title: str,
    content: str,
    thread_id: str | None = None,
) -> int:
    if retrieval_index is None or embedding_provider is None:
        return 0
    artifact_hash = artifact_content_hash(content)
    chunks = artifact_chunks(content)
    vectors = embed_texts_batched(embedding_provider, chunks)
    for chunk_index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
        upsert_embedded_document(
            retrieval_index=retrieval_index,
            embedding_provider=embedding_provider,
            collection="focus_artifact_chunks",
            doc_id=f"artifact:{artifact_id}:{chunk_index}",
            source_id=artifact_id,
            text=chunk,
            vector=vector,
            fields={
                "source_type": "artifact",
                "artifact_id": artifact_id,
                "title": title,
                "thread_id": thread_id or "",
                "chunk_index": chunk_index,
                "artifact_hash": artifact_hash,
            },
        )
    return len(chunks)


def artifact_chunks(content: str, *, chunk_chars: int = 1200) -> list[str]:
    text = content.strip()
    if not text:
        return []
    return [text[index : index + chunk_chars] for index in range(0, len(text), chunk_chars)]


def artifact_content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()
