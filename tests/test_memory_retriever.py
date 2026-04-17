from types import SimpleNamespace

from focus_agent.core.request_context import RequestContext
from focus_agent.core.types import PromptMode
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
