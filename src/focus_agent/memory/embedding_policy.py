from __future__ import annotations

from .models import MemoryKind, MemoryRecord, MemoryStatus


class MemoryEmbeddingPolicy:
    """Decide which durable memories should receive semantic embeddings."""

    semantic_kinds = {
        MemoryKind.USER_PREFERENCE,
        MemoryKind.USER_PROFILE,
        MemoryKind.PROJECT_FACT,
        MemoryKind.IMPORTED_CONCLUSION,
    }

    def should_embed(self, record: MemoryRecord) -> bool:
        if record.status != MemoryStatus.ACTIVE or record.deleted_at is not None:
            return False
        if not _has_embedding_text(record):
            return False
        if record.summary == "[forgotten]" and not record.content:
            return False
        if record.kind in self.semantic_kinds:
            return True
        return record.kind == MemoryKind.BRANCH_FINDING and bool(record.promoted_to_main)


def should_embed_memory(record: MemoryRecord) -> bool:
    return MemoryEmbeddingPolicy().should_embed(record)


def _has_embedding_text(record: MemoryRecord) -> bool:
    return bool(
        str(record.summary or "").strip()
        or str(record.content or "").strip()
        or record.tags
        or record.evidence_refs
    )


__all__ = ["MemoryEmbeddingPolicy", "should_embed_memory"]
