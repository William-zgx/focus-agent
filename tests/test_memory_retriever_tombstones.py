from __future__ import annotations

from types import SimpleNamespace

from focus_agent.core.request_context import RequestContext
from focus_agent.core.types import PromptMode
from focus_agent.memory import MemoryRetriever

from .test_memory_retriever import MultiHitStore


def test_legacy_store_hydration_preserves_forgotten_status_and_deleted_at():
    namespace = ("conversation", "root-1", "main")

    def record(key, status, summary, deleted_at=None):
        return SimpleNamespace(
            key=key,
            namespace=namespace,
            score=0.8,
            value={
                "kind": "project_fact",
                "scope": "root_thread",
                "content": summary,
                "summary": summary,
                "root_thread_id": "root-1",
                "user_id": "user-1",
                "status": status,
                "deleted_at": deleted_at,
            },
        )

    retriever = MemoryRetriever(
        store=MultiHitStore(
            {
                namespace: [
                    record(
                        "forgotten-release-marker",
                        "forgotten",
                        "release marker stale decision",
                        "2026-11-22T00:00:00+00:00",
                    ),
                    record("active-release-marker", "active", "release marker current decision"),
                ]
            }
        ),
        default_limit=1,
    )

    bundle = retriever.retrieve_for_turn(
        context=RequestContext(user_id="user-1", root_thread_id="root-1"),
        state={},
        query="release marker",
        prompt_mode=PromptMode.EXPLORE,
    )

    assert [hit.record.memory_id for hit in bundle.hits] == ["active-release-marker"]


def test_legacy_invalid_tombstone_fields_skip_only_the_invalid_record():
    namespace = ("conversation", "root-1", "main")

    def raw_record(key, status, deleted_at, summary):
        return SimpleNamespace(
            key=key,
            namespace=namespace,
            score=0.8,
            value={
                "kind": "project_fact",
                "scope": "root_thread",
                "content": summary,
                "summary": summary,
                "root_thread_id": "root-1",
                "user_id": "user-1",
                "status": status,
                "deleted_at": deleted_at,
            },
        )

    retriever = MemoryRetriever(
        store=MultiHitStore(
            {
                namespace: [
                    raw_record("invalid-status", "deleted", None, "release marker invalid"),
                    raw_record(
                        "invalid-timestamp",
                        "active",
                        "not-a-timestamp",
                        "release marker also invalid",
                    ),
                    raw_record("valid-active", "active", None, "release marker valid"),
                ]
            }
        )
    )

    bundle = retriever.retrieve_for_turn(
        context=RequestContext(user_id="user-1", root_thread_id="root-1"),
        state={},
        query="release marker",
        prompt_mode=PromptMode.EXPLORE,
    )

    assert [hit.record.memory_id for hit in bundle.hits] == ["valid-active"]
