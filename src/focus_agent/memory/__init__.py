"""Structured memory models plus compatibility exports for legacy helpers."""

from .dedupe import memory_fingerprint, merge_duplicate_records
from .assembler import build_memory_blocks, render_memory_block
from .extractor import MemoryExtractor
from .models import (
    MemoryExtractionResult,
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemorySearchHit,
    MemoryVisibility,
    MemoryWriteRequest,
    RetrievedMemoryBundle,
)
from .policy import MemoryPolicy
from .retriever import MemoryRetriever
from .scorer import score_memory_hit, score_memory_importance
from .writer import MemoryWriter
from ..storage.import_memory import (
    branch_memory_namespace,
    main_conversation_namespace,
    persist_imported_conclusion,
    user_profile_memory_namespace,
)

__all__ = [
    "MemoryExtractionResult",
    "MemoryExtractor",
    "MemoryKind",
    "MemoryPolicy",
    "MemoryRecord",
    "MemoryRetriever",
    "MemoryScope",
    "MemorySearchHit",
    "MemoryVisibility",
    "MemoryWriteRequest",
    "MemoryWriter",
    "RetrievedMemoryBundle",
    "branch_memory_namespace",
    "main_conversation_namespace",
    "build_memory_blocks",
    "memory_fingerprint",
    "merge_duplicate_records",
    "persist_imported_conclusion",
    "render_memory_block",
    "score_memory_hit",
    "score_memory_importance",
    "user_profile_memory_namespace",
]
