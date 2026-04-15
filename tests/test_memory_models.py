from focus_agent.core.types import PromptMode
from focus_agent.memory import (
    MemoryExtractionResult,
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemorySearchHit,
    MemoryVisibility,
    MemoryWriteRequest,
    RetrievedMemoryBundle,
    memory_fingerprint,
    merge_duplicate_records,
    score_memory_hit,
    score_memory_importance,
)


def test_memory_models_have_safe_defaults():
    record = MemoryRecord(
        memory_id="mem-1",
        kind=MemoryKind.BRANCH_FINDING,
        scope=MemoryScope.BRANCH,
        content="发现一个稳定接口边界",
    )
    bundle = RetrievedMemoryBundle(query="接口边界")
    extraction = MemoryExtractionResult()

    assert record.visibility == MemoryVisibility.PRIVATE
    assert record.tags == []
    assert bundle.hits == []
    assert bundle.total_hits == 0
    assert extraction.records == []
    assert extraction.skipped_reasons == []


def test_memory_fingerprint_is_stable_for_equivalent_requests():
    first = MemoryWriteRequest(
        kind=MemoryKind.PROJECT_FACT,
        scope=MemoryScope.PROJECT,
        visibility=MemoryVisibility.SHARED,
        namespace=("project", "demo", "memory"),
        content="项目要求输出中英双语界面",
        summary="双语界面要求",
        tags=["ui", "i18n"],
        evidence_refs=["spec-1"],
        root_thread_id="root-1",
        user_id="user-1",
    )
    second = MemoryWriteRequest.model_validate(first.model_dump())

    assert memory_fingerprint(first) == memory_fingerprint(second)


def test_merge_duplicate_records_preserves_history_and_merges_strength():
    existing = MemoryRecord(
        memory_id="mem-1",
        kind=MemoryKind.BRANCH_FINDING,
        scope=MemoryScope.BRANCH,
        visibility=MemoryVisibility.PROMOTABLE,
        namespace=("conversation", "root-1", "branch", "branch-1", "local_memory"),
        content="先验证 API 形状",
        summary="验证 API",
        tags=["api"],
        evidence_refs=["doc-1"],
        confidence=0.6,
        importance=0.5,
    )
    incoming = MemoryWriteRequest(
        kind=MemoryKind.BRANCH_FINDING,
        scope=MemoryScope.BRANCH,
        visibility=MemoryVisibility.PROMOTABLE,
        namespace=("conversation", "root-1", "branch", "branch-1", "local_memory"),
        content="先验证 API 形状",
        summary="验证 API 兼容性",
        tags=["api", "compat"],
        evidence_refs=["doc-1", "test-2"],
        confidence=0.9,
        importance=0.8,
        promoted_to_main=True,
    )

    merged = merge_duplicate_records(existing, incoming)

    assert merged.memory_id == "mem-1"
    assert merged.summary == "验证 API 兼容性"
    assert merged.tags == ["api", "compat"]
    assert merged.evidence_refs == ["doc-1", "test-2"]
    assert merged.confidence == 0.9
    assert merged.importance == 0.8
    assert merged.promoted_to_main is True
    assert merged.fingerprint


def test_memory_scoring_reflects_mode_and_write_context():
    record = MemoryRecord(
        memory_id="mem-1",
        kind=MemoryKind.IMPORTED_CONCLUSION,
        scope=MemoryScope.ROOT_THREAD,
        visibility=MemoryVisibility.SHARED,
        namespace=("conversation", "root-1", "main"),
        content="已确认这条发现可以进入主线",
        summary="确认导入主线",
        confidence=0.9,
        importance=0.75,
        promoted_to_main=True,
    )
    hit = MemorySearchHit(
        record=record,
        score=0.4,
        matched_terms=["确认", "主线"],
        namespace=record.namespace,
    )
    request = MemoryWriteRequest(
        kind=MemoryKind.IMPORTED_CONCLUSION,
        scope=MemoryScope.ROOT_THREAD,
        visibility=MemoryVisibility.SHARED,
        namespace=record.namespace,
        content="当前 active goal 需要确认主线导入",
        summary="主线导入",
        evidence_refs=["merge-1", "proposal-1"],
        importance=0.5,
    )

    hit_score = score_memory_hit(hit, query="确认导入主线", prompt_mode=PromptMode.BRANCH_REVIEW)
    importance_score = score_memory_importance(request, state={"active_goal": "确认主线导入"})

    assert hit_score > 0.4
    assert 0.5 < importance_score <= 1.0
