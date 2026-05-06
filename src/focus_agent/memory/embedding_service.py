from __future__ import annotations

from .embedding import MemoryEmbeddingService

MemoryEmbeddingWriteResult = dict[str, object]

__all__ = ["MemoryEmbeddingService", "MemoryEmbeddingWriteResult"]
