from types import SimpleNamespace

from focus_agent.core.request_context import RequestContext
from focus_agent.core.types import Plan, PlanStep, PromptMode
from focus_agent.memory import MemoryRetriever


class FakeStore:
    def search(self, namespace, query, limit):
        del namespace, query, limit
        return [
            SimpleNamespace(
                key="mem-1",
                namespace=("conversation", "root-1", "main"),
                score=0.4,
                value={
                    "kind": "project_fact",
                    "scope": "root_thread",
                    "content": "鲁迅的文笔偏冷峻、凝练。",
                    "summary": "鲁迅文笔特点",
                    "created_at": None,
                    "updated_at": None,
                },
            )
        ]


def test_memory_retriever_tolerates_missing_timestamps():
    retriever = MemoryRetriever(store=FakeStore())
    context = RequestContext(user_id="user-1", root_thread_id="root-1")

    bundle = retriever.retrieve_for_turn(
        context=context,
        state={},
        query="鲁迅 文笔",
        prompt_mode=PromptMode.EXPLORE,
    )

    assert bundle.total_hits == 1
    assert bundle.hits[0].record.summary == "鲁迅文笔特点"
    assert bundle.hits[0].record.created_at is not None
    assert bundle.hits[0].record.updated_at is not None


class MultiHitStore:
    def __init__(self, hits):
        self.hits = hits

    def search(self, namespace, query, limit):  # noqa: ARG002
        namespace_key = tuple(namespace)
        return self.hits.get(namespace_key, [])[:limit]


class QueryCapturingStore:
    def __init__(self, hit):
        self.hit = hit
        self.queries = []

    def search(self, namespace, query, limit):  # noqa: ARG002
        self.queries.append((tuple(namespace), query))
        return [self.hit]


def test_memory_retriever_prefers_promoted_branch_memory_for_same_finding():
    branch_namespace = ("conversation", "root-1", "branch", "branch-1", "local_memory")
    main_namespace = ("conversation", "root-1", "main")
    store = MultiHitStore(
        {
            branch_namespace: [
                SimpleNamespace(
                    key="branch-mem",
                    namespace=branch_namespace,
                    score=0.72,
                    value={
                        "kind": "branch_finding",
                        "scope": "branch",
                        "visibility": "promotable",
                        "content": "发现 owner 字段在首次加载时会丢失。",
                        "summary": "owner 字段首次加载丢失",
                        "root_thread_id": "root-1",
                        "source_branch_id": "branch-1",
                        "promoted_to_main": False,
                        "confidence": 0.78,
                    },
                )
            ],
            main_namespace: [
                SimpleNamespace(
                    key="main-mem",
                    namespace=main_namespace,
                    score=0.71,
                    value={
                        "kind": "branch_finding",
                        "scope": "root_thread",
                        "visibility": "shared",
                        "content": "发现 owner 字段在首次加载时会丢失。",
                        "summary": "owner 字段首次加载丢失",
                        "root_thread_id": "root-1",
                        "source_branch_id": "branch-1",
                        "promoted_to_main": True,
                        "confidence": 0.72,
                    },
                )
            ],
        }
    )
    retriever = MemoryRetriever(store=store)
    context = RequestContext(user_id="user-1", root_thread_id="root-1", branch_id="branch-1")

    bundle = retriever.retrieve_for_turn(
        context=context,
        state={},
        query="owner 字段",
        prompt_mode=PromptMode.EXPLORE,
    )

    assert bundle.total_hits == 1
    assert bundle.hits[0].record.promoted_to_main is True
    assert bundle.hits[0].record.scope.value == "root_thread"


def test_memory_retriever_prefers_latest_user_preference_in_same_topic():
    profile_namespace = ("user", "user-1", "profile")
    store = MultiHitStore(
        {
            profile_namespace: [
                SimpleNamespace(
                    key="pref-old",
                    namespace=profile_namespace,
                    score=0.69,
                    value={
                        "kind": "user_preference",
                        "scope": "user",
                        "visibility": "shared",
                        "content": "请用中文回答。",
                        "summary": "请用中文回答。",
                        "user_id": "user-1",
                        "updated_at": "2026-04-22T08:00:00+00:00",
                    },
                ),
                SimpleNamespace(
                    key="pref-new",
                    namespace=profile_namespace,
                    score=0.67,
                    value={
                        "kind": "user_preference",
                        "scope": "user",
                        "visibility": "shared",
                        "content": "请用英文回答。",
                        "summary": "请用英文回答。",
                        "user_id": "user-1",
                        "updated_at": "2026-04-22T09:00:00+00:00",
                    },
                ),
            ]
        }
    )
    retriever = MemoryRetriever(store=store)
    context = RequestContext(user_id="user-1", root_thread_id="root-1")

    bundle = retriever.retrieve_for_turn(
        context=context,
        state={},
        query="请用什么语言回答",
        prompt_mode=PromptMode.EXPLORE,
    )

    assert bundle.total_hits == 1
    assert bundle.hits[0].record.content == "请用英文回答。"


def test_memory_retriever_filters_synthesize_to_durable_memories_first():
    branch_namespace = ("conversation", "root-1", "branch", "branch-1", "local_memory")
    main_namespace = ("conversation", "root-1", "main")
    profile_namespace = ("user", "user-1", "profile")
    store = MultiHitStore(
        {
            branch_namespace: [
                SimpleNamespace(
                    key="branch-mem",
                    namespace=branch_namespace,
                    score=0.86,
                    value={
                        "kind": "branch_finding",
                        "scope": "branch",
                        "visibility": "promotable",
                        "content": "本地分支里还有一条待确认 finding。",
                        "summary": "待确认 branch finding",
                        "root_thread_id": "root-1",
                        "source_branch_id": "branch-1",
                        "promoted_to_main": False,
                    },
                )
            ],
            main_namespace: [
                SimpleNamespace(
                    key="main-mem",
                    namespace=main_namespace,
                    score=0.84,
                    value={
                        "kind": "imported_conclusion",
                        "scope": "root_thread",
                        "visibility": "shared",
                        "content": "已批准的主线结论。",
                        "summary": "approved main finding",
                        "root_thread_id": "root-1",
                        "promoted_to_main": True,
                    },
                )
            ],
            profile_namespace: [
                SimpleNamespace(
                    key="user-pref",
                    namespace=profile_namespace,
                    score=0.82,
                    value={
                        "kind": "user_preference",
                        "scope": "user",
                        "visibility": "shared",
                        "content": "请用英文回答。",
                        "summary": "请用英文回答。",
                        "user_id": "user-1",
                    },
                )
            ],
        }
    )
    retriever = MemoryRetriever(store=store)
    context = RequestContext(user_id="user-1", root_thread_id="root-1", branch_id="branch-1")

    bundle = retriever.retrieve_for_turn(
        context=context,
        state={},
        query="请基于已确认结论继续回答",
        prompt_mode=PromptMode.SYNTHESIZE,
    )

    assert bundle.total_hits == 2
    assert [hit.record.kind.value for hit in bundle.hits] == ["user_preference", "imported_conclusion"]


def test_memory_retriever_prefers_branch_findings_in_branch_review_mode():
    branch_namespace = ("conversation", "root-1", "branch", "branch-1", "local_memory")
    main_namespace = ("conversation", "root-1", "main")
    store = MultiHitStore(
        {
            branch_namespace: [
                SimpleNamespace(
                    key="branch-mem",
                    namespace=branch_namespace,
                    score=0.72,
                    value={
                        "kind": "branch_finding",
                        "scope": "branch",
                        "visibility": "promotable",
                        "content": "待 review 的本地 finding A",
                        "summary": "本地 finding A",
                        "root_thread_id": "root-1",
                        "source_branch_id": "branch-1",
                        "promoted_to_main": False,
                    },
                )
            ],
            main_namespace: [
                SimpleNamespace(
                    key="main-mem",
                    namespace=main_namespace,
                    score=0.82,
                    value={
                        "kind": "imported_conclusion",
                        "scope": "root_thread",
                        "visibility": "shared",
                        "content": "已进入主线的 finding B",
                        "summary": "主线 finding B",
                        "root_thread_id": "root-1",
                        "promoted_to_main": True,
                    },
                )
            ],
        }
    )
    retriever = MemoryRetriever(store=store)
    context = RequestContext(user_id="user-1", root_thread_id="root-1", branch_id="branch-1")

    bundle = retriever.retrieve_for_turn(
        context=context,
        state={},
        query="review finding",
        prompt_mode=PromptMode.BRANCH_REVIEW,
    )

    assert bundle.total_hits == 2
    assert bundle.hits[0].record.scope.value == "branch"


def test_memory_retriever_expands_query_with_goal_task_and_plan_step():
    namespace = ("conversation", "root-1", "main")
    store = QueryCapturingStore(
        SimpleNamespace(
            key="main-mem",
            namespace=namespace,
            score=0.5,
            value={
                "kind": "project_fact",
                "scope": "project",
                "visibility": "shared",
                "content": "owner 字段需要在首屏列表里展示。",
                "summary": "owner 字段展示要求",
                "root_thread_id": "root-1",
            },
        )
    )
    retriever = MemoryRetriever(store=store)
    context = RequestContext(user_id="user-1", root_thread_id="root-1", project_id="proj-1")

    bundle = retriever.retrieve_for_turn(
        context=context,
        state={
            "active_goal": "修复 owner 字段丢失",
            "task_brief": "检查首屏列表和 owner 字段",
            "plan": Plan(
                steps=[PlanStep(id="s1", goal="定位 owner 字段在首屏列表的渲染路径")],
                success_criteria="owner visible",
            ),
            "current_step_id": "s1",
        },
        query="owner 字段",
        prompt_mode=PromptMode.EXECUTE,
    )

    assert "修复 owner 字段丢失" in bundle.query
    assert "检查首屏列表和 owner 字段" in bundle.query
    assert "定位 owner 字段在首屏列表的渲染路径" in bundle.query
    assert any("修复 owner 字段丢失" in query for _, query in store.queries)


def test_memory_retriever_extracts_matched_terms_for_chinese_query_without_spaces():
    namespace = ("conversation", "root-1", "main")
    store = QueryCapturingStore(
        SimpleNamespace(
            key="user-pref",
            namespace=namespace,
            score=0.5,
            value={
                "kind": "user_preference",
                "scope": "user",
                "visibility": "shared",
                "content": "请用英文回答。",
                "summary": "请用英文回答。",
                "user_id": "user-1",
            },
        )
    )
    retriever = MemoryRetriever(store=store)
    context = RequestContext(user_id="user-1", root_thread_id="root-1")

    bundle = retriever.retrieve_for_turn(
        context=context,
        state={},
        query="请用什么语言回答",
        prompt_mode=PromptMode.EXPLORE,
    )

    assert bundle.hits[0].matched_terms
