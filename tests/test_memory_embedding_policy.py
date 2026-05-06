from __future__ import annotations

from datetime import datetime, timezone

import pytest

from focus_agent.memory.embedding_policy import MemoryEmbeddingPolicy, should_embed_memory
from focus_agent.memory.models import (
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
    MemoryVisibility,
)


def _record(
    *,
    kind: MemoryKind,
    content: str = "durable semantic fact",
    summary: str = "durable semantic fact",
    promoted_to_main: bool = False,
    status: MemoryStatus = MemoryStatus.ACTIVE,
    deleted: bool = False,
) -> MemoryRecord:
    return MemoryRecord(
        memory_id=f"mem-{kind.value}",
        kind=kind,
        scope=MemoryScope.ROOT_THREAD,
        visibility=MemoryVisibility.PRIVATE,
        namespace=("conversation", "root-1", "main"),
        content=content,
        summary=summary,
        root_thread_id="root-1",
        promoted_to_main=promoted_to_main,
        status=status,
        deleted_at=datetime.now(timezone.utc) if deleted else None,
    )


@pytest.mark.parametrize(
    "kind",
    [
        MemoryKind.USER_PREFERENCE,
        MemoryKind.USER_PROFILE,
        MemoryKind.PROJECT_FACT,
        MemoryKind.IMPORTED_CONCLUSION,
    ],
)
def test_memory_embedding_policy_embeds_long_term_semantic_kinds(kind: MemoryKind) -> None:
    assert MemoryEmbeddingPolicy().should_embed(_record(kind=kind)) is True


@pytest.mark.parametrize(
    "kind",
    [
        MemoryKind.TURN_SUMMARY,
        MemoryKind.TOOL_OBSERVATION,
        MemoryKind.ARTIFACT,
        MemoryKind.CITATION,
    ],
)
def test_memory_embedding_policy_skips_short_term_and_non_semantic_kinds(kind: MemoryKind) -> None:
    assert MemoryEmbeddingPolicy().should_embed(_record(kind=kind)) is False


def test_memory_embedding_policy_embeds_only_promoted_branch_findings() -> None:
    assert MemoryEmbeddingPolicy().should_embed(
        _record(kind=MemoryKind.BRANCH_FINDING, promoted_to_main=True)
    )
    assert not MemoryEmbeddingPolicy().should_embed(
        _record(kind=MemoryKind.BRANCH_FINDING, promoted_to_main=False)
    )


@pytest.mark.parametrize(
    "record",
    [
        _record(kind=MemoryKind.PROJECT_FACT, status=MemoryStatus.FORGOTTEN),
        _record(kind=MemoryKind.PROJECT_FACT, deleted=True),
        _record(kind=MemoryKind.PROJECT_FACT, content="", summary=""),
        _record(kind=MemoryKind.PROJECT_FACT, content="", summary="[forgotten]"),
    ],
)
def test_memory_embedding_policy_skips_inactive_or_empty_records(record: MemoryRecord) -> None:
    assert should_embed_memory(record) is False
