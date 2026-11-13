import pytest

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
    memory_resolution_key,
    memory_semantic_key,
    merge_duplicate_records,
    score_memory_hit,
    score_memory_importance,
)
from focus_agent.memory.dedupe import is_possible_memory_conflict, should_replace_memory
from focus_agent.storage.namespaces import (
    branch_local_memory_namespace,
    conversation_main_namespace,
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


def test_memory_semantic_key_is_stable_across_branch_promotion():
    branch_record = MemoryWriteRequest(
        kind=MemoryKind.BRANCH_FINDING,
        scope=MemoryScope.BRANCH,
        visibility=MemoryVisibility.PROMOTABLE,
        namespace=branch_local_memory_namespace("root-1", "branch-1"),
        content="先修复 owner 字段竞态",
        summary="修复 owner 竞态",
        root_thread_id="root-1",
        source_branch_id="branch-1",
        user_id="user-1",
    )
    promoted_record = MemoryWriteRequest(
        kind=MemoryKind.BRANCH_FINDING,
        scope=MemoryScope.ROOT_THREAD,
        visibility=MemoryVisibility.SHARED,
        namespace=conversation_main_namespace("root-1"),
        content="先修复 owner 字段竞态",
        summary="修复 owner 竞态",
        root_thread_id="root-1",
        source_branch_id="branch-1",
        user_id="user-1",
        promoted_to_main=True,
    )

    assert memory_semantic_key(branch_record) == memory_semantic_key(promoted_record)


def test_memory_resolution_key_groups_same_user_preference_topic():
    first = MemoryWriteRequest(
        kind=MemoryKind.USER_PREFERENCE,
        scope=MemoryScope.USER,
        visibility=MemoryVisibility.SHARED,
        namespace=("user", "user-1", "profile"),
        content="请用中文回答。",
        summary="请用中文回答。",
        user_id="user-1",
    )
    second = MemoryWriteRequest(
        kind=MemoryKind.USER_PREFERENCE,
        scope=MemoryScope.USER,
        visibility=MemoryVisibility.SHARED,
        namespace=("user", "user-1", "profile"),
        content="请用英文回答。",
        summary="请用英文回答。",
        user_id="user-1",
    )

    assert memory_resolution_key(first) == memory_resolution_key(second)


def _memory_policy_pair(
    existing_text: str,
    incoming_text: str,
    *,
    kind: MemoryKind = MemoryKind.USER_PROFILE,
    scope: MemoryScope = MemoryScope.USER,
) -> tuple[MemoryRecord, MemoryWriteRequest]:
    shared = {
        "kind": kind,
        "scope": scope,
        "visibility": MemoryVisibility.SHARED,
        "namespace": ("policy", "test"),
    }
    existing = MemoryRecord(
        memory_id="mem-policy",
        content=existing_text,
        summary=existing_text,
        confidence=0.5,
        importance=0.5,
        **shared,
    )
    incoming = MemoryWriteRequest(
        content=incoming_text,
        summary=incoming_text,
        confidence=0.5,
        importance=0.5,
        **shared,
    )
    return existing, incoming


def test_memory_replacement_policy_latest_wins_only_for_user_preferences():
    preference, preference_update = _memory_policy_pair(
        "请用中文回答。",
        "请用英文回答。",
        kind=MemoryKind.USER_PREFERENCE,
    )
    profile, profile_update = _memory_policy_pair(
        "我的母语是中文",
        "工作语言为英文",
    )

    assert is_possible_memory_conflict(preference, preference_update)
    assert should_replace_memory(preference, preference_update)
    assert is_possible_memory_conflict(profile, profile_update)
    assert not should_replace_memory(profile, profile_update)


def test_memory_replacement_policy_allows_project_overlap_only():
    existing, incoming = _memory_policy_pair(
        "Project deploys from the release branch.",
        "Project deploys from the main branch.",
        kind=MemoryKind.PROJECT_FACT,
        scope=MemoryScope.PROJECT,
    )

    assert is_possible_memory_conflict(existing, incoming)
    assert should_replace_memory(existing, incoming)


def test_memory_replacement_policy_preserves_unrelated_project_conflict():
    existing, incoming = _memory_policy_pair(
        "Release owner is platform operations.",
        "Database migrations require review.",
        kind=MemoryKind.PROJECT_FACT,
        scope=MemoryScope.PROJECT,
    )

    assert is_possible_memory_conflict(existing, incoming)
    assert not should_replace_memory(existing, incoming)


@pytest.mark.parametrize(
    "incoming_update",
    [
        {"importance": 0.9},
        {"confidence": 0.9},
        {
            "content": "更正：数据库迁移需要评审。",
            "summary": "更正：数据库迁移需要评审。",
        },
    ],
)
def test_memory_replacement_policy_honors_strength_and_correction_signals(incoming_update):
    existing, incoming = _memory_policy_pair(
        "Release owner is platform operations.",
        "Database migrations require review.",
        kind=MemoryKind.PROJECT_FACT,
        scope=MemoryScope.PROJECT,
    )
    incoming = incoming.model_copy(update=incoming_update)

    assert should_replace_memory(existing, incoming)


def test_memory_conflict_policy_rejects_different_kind_scope_and_branch_records():
    existing, incoming = _memory_policy_pair(
        "Existing stable fact.",
        "Incoming changed fact.",
    )
    branch_existing, branch_incoming = _memory_policy_pair(
        "Existing branch finding.",
        "Incoming branch finding.",
        kind=MemoryKind.BRANCH_FINDING,
        scope=MemoryScope.BRANCH,
    )

    assert is_possible_memory_conflict(existing, incoming)
    assert not is_possible_memory_conflict(
        existing,
        incoming.model_copy(update={"kind": MemoryKind.USER_PREFERENCE}),
    )
    assert not is_possible_memory_conflict(
        existing,
        incoming.model_copy(update={"scope": MemoryScope.PROJECT}),
    )
    assert not is_possible_memory_conflict(branch_existing, branch_incoming)


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
    assert merged.semantic_key


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
