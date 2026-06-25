from types import SimpleNamespace

from focus_agent.retrieval import InMemoryRetrievalIndex, RetrievalDocument
from focus_agent.retrieval.artifacts import index_artifact_content
from focus_agent.retrieval.trajectory import index_trajectory_record, search_trajectory


class _FakeEmbeddingProvider:
    def embed(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


def test_in_memory_retrieval_index_filters_and_scores_documents():
    index = InMemoryRetrievalIndex()
    index.upsert(
        RetrievalDocument(
            collection="focus_memory",
            doc_id="memory:1",
            source_id="1",
            text="zvec semantic memory",
            fields={"namespace": ("conversation", "root-1", "main"), "status": "active"},
        )
    )

    hits = index.search(
        collection="focus_memory",
        query="semantic",
        limit=5,
        filters={"namespace": ("conversation", "root-1", "main"), "status": "active"},
    )

    assert [hit.source_id for hit in hits] == ["1"]


def test_trajectory_record_indexes_turn_and_steps():
    index = InMemoryRetrievalIndex()
    record = SimpleNamespace(
        id="turn-1",
        thread_id="thread-1",
        root_thread_id="root-1",
        status="success",
        kind="chat.turn",
        scene="technical_deep_dive",
        task_brief="Migrate retrieval to Zvec",
        user_message="How should we migrate RAG?",
        answer="Use Zvec with fallback.",
        error=None,
        plan_meta={},
        trajectory=[
            SimpleNamespace(
                tool="search_code",
                args={"query": "retrieval"},
                observation="found retrieval code",
                error=None,
            )
        ],
    )

    index_trajectory_record(
        retrieval_index=index,
        embedding_provider=_FakeEmbeddingProvider(),
        record=record,
    )
    hits = search_trajectory(
        retrieval_index=index,
        embedding_provider=_FakeEmbeddingProvider(),
        query="retrieval Zvec",
    )

    assert {hit.doc_id for hit in hits} == {
        "trajectory:turn-1:turn",
        "trajectory:turn-1:step:0",
    }


def test_artifact_content_indexes_chunks_with_hash_metadata():
    index = InMemoryRetrievalIndex()

    chunk_count = index_artifact_content(
        retrieval_index=index,
        embedding_provider=_FakeEmbeddingProvider(),
        artifact_id="notes.md",
        title="Notes",
        content=f"{'alpha ' * 240}beta marker",
        thread_id="thread-1",
    )

    hits = index.search(
        collection="focus_artifact_chunks",
        query="beta marker",
        vector=[1.0, 0.0, 0.0],
        limit=5,
    )

    assert chunk_count == 2
    assert hits[0].fields["artifact_id"] == "notes.md"
    assert hits[0].fields["thread_id"] == "thread-1"
    assert hits[0].fields["artifact_hash"]
