from __future__ import annotations

from datetime import UTC, datetime

from focus_agent.core.request_context import RequestContext
from focus_agent.core.types import PromptMode
from focus_agent.engine.local_persistence import PersistentInMemoryStore
from focus_agent.eval.memory_layers import (
    evaluate_memory_layer_observation,
    evaluate_memory_layer_suite,
)
from focus_agent.memory import MemoryRetriever, MemoryWriter, render_memory_block
from focus_agent.memory.assembler import render_scoped_context_memories
from focus_agent.memory.models import (
    MemoryKind,
    MemoryScope,
    MemoryVisibility,
    MemoryWriteRequest,
)
from focus_agent.memory.service import MemoryService
from focus_agent.retrieval import InMemoryRetrievalIndex, RetrievalDocument
from focus_agent.storage.namespaces import conversation_main_namespace, project_memory_namespace

from ..test_memory_service import _FakeMemoryRepository


def _request(
    *,
    namespace,
    content: str,
    user_id: str = "user-a",
    root_thread_id: str = "root-a",
    scope: MemoryScope = MemoryScope.ROOT_THREAD,
    semantic_key: str | None = None,
    importance: float = 0.5,
) -> MemoryWriteRequest:
    kind = MemoryKind.PROJECT_FACT if scope == MemoryScope.PROJECT else MemoryKind.TURN_SUMMARY
    return MemoryWriteRequest(
        kind=kind,
        scope=scope,
        visibility=MemoryVisibility.SHARED,
        namespace=namespace,
        content=content,
        summary=content,
        user_id=user_id,
        root_thread_id=root_thread_id,
        semantic_key=semantic_key,
        importance=importance,
    )


def _observation(
    case_id: str,
    *,
    records,
    bundle,
    context: RequestContext,
    expected: dict,
    scoped_records=None,
    recreated_record_ids=(),
) -> dict:
    records = list(records)
    serialized = [
        record.model_dump(mode="json") if hasattr(record, "model_dump") else dict(record)
        for record in records
    ]
    scoped = (
        [
            {
                **(
                    record.model_dump(mode="json")
                    if hasattr(record, "model_dump")
                    else dict(record)
                ),
                "score": 0.5,
            }
            for record in scoped_records
        ]
        if scoped_records is not None
        else [
            {
                **hit.record.model_dump(mode="json"),
                "score": hit.score,
            }
            for hit in bundle.hits
        ]
    )
    return {
        "case_id": case_id,
        "write": {"records": serialized},
        "retrieval": {
            "selected_memory_ids": [hit.record.memory_id for hit in bundle.hits],
            "retrieval_plan": bundle.retrieval_plan,
        },
        "use": {
            "prompt": render_memory_block(bundle),
            "scoped_prompt": render_scoped_context_memories(
                {"retrieved_memories": scoped},
                prompt_mode=PromptMode.EXPLORE,
                represented_lines=[],
                fallback="",
                user_id=context.user_id,
                root_thread_id=context.root_thread_id,
            ),
        },
        "expected": expected,
        "recreated_record_ids": list(recreated_record_ids),
    }


def test_three_writes_keep_only_the_newest_decision_in_every_layer():
    repository = _FakeMemoryRepository()
    service = MemoryService(repository=repository)
    retriever = MemoryRetriever(repository=repository)
    context = RequestContext(user_id="user-a", root_thread_id="root-a", project_id="project-1")
    namespace = project_memory_namespace("project-1")
    base = _request(
        namespace=namespace,
        content="release decision DECISION_OLD_V1",
        scope=MemoryScope.PROJECT,
        semantic_key="release-decision",
    )
    first = service.upsert_request(base)
    service.upsert_request(
        base.model_copy(
            update={
                "content": "release decision DECISION_STALE_V2",
                "summary": "release decision DECISION_STALE_V2",
                "importance": 0.6,
            }
        )
    )
    third = service.upsert_request(
        base.model_copy(
            update={
                "content": "release decision DECISION_CURRENT_V3",
                "summary": "release decision DECISION_CURRENT_V3",
                "importance": 0.7,
            }
        )
    )
    bundle = retriever.retrieve_for_turn(
        context=context,
        state={},
        query="release decision",
        prompt_mode=PromptMode.EXPLORE,
    )
    observation = _observation(
        "stale-decision",
        records=repository.records.values(),
        bundle=bundle,
        context=context,
        expected={
            "active_record_count": 1,
            "selected_memory_ids": [first.memory_id],
            "required_use_markers": ["DECISION_CURRENT_V3"],
            "stale_decision_markers": ["DECISION_OLD_V1", "DECISION_STALE_V2"],
        },
    )

    report = evaluate_memory_layer_observation(observation)
    assert third.memory_id == first.memory_id
    assert report["passed"] is True, report


def test_cross_owner_records_fail_closed_at_retrieval_and_scoped_use():
    repository = _FakeMemoryRepository()
    service = MemoryService(repository=repository)
    retriever = MemoryRetriever(repository=repository)
    own_context = RequestContext(user_id="user-a", root_thread_id="root-a")
    own = service.upsert_request(
        _request(
            namespace=conversation_main_namespace("root-a"),
            content="owner marker OWN_CURRENT",
        )
    )
    foreign = service.upsert_request(
        _request(
            namespace=conversation_main_namespace("root-b"),
            content="owner marker FOREIGN_SECRET",
            user_id="user-b",
            root_thread_id="root-b",
        )
    )
    bundle = retriever.retrieve_for_turn(
        context=own_context,
        state={},
        query="owner marker",
        prompt_mode=PromptMode.EXPLORE,
    )
    records = [repository.records[own.memory_id], repository.records[foreign.memory_id]]
    observation = _observation(
        "cross-owner",
        records=records,
        bundle=bundle,
        context=own_context,
        scoped_records=records,
        expected={
            "active_record_count": 2,
            "selected_memory_ids": [own.memory_id],
            "required_use_markers": ["OWN_CURRENT"],
            "foreign_memory_ids": [foreign.memory_id],
            "foreign_markers": ["FOREIGN_SECRET"],
        },
    )

    report = evaluate_memory_layer_observation(observation)
    assert report["passed"] is True, report
    observation["retrieval"]["selected_memory_ids"].append(foreign.memory_id)
    observation["use"]["scoped_prompt"] += "FOREIGN_SECRET"
    failed = evaluate_memory_layer_observation(observation)
    assert failed["passed"] is False
    assert "cross_owner_memory_selected" in failed["hard_stop_violations"][0]
    assert any("cross_owner_marker_in_use" in item for item in failed["hard_stop_violations"])


def test_forget_with_stale_index_cannot_resurrect_or_render_the_old_record():
    repository = _FakeMemoryRepository()
    service = MemoryService(repository=repository)
    context = RequestContext(user_id="user-a", root_thread_id="root-a")
    namespace = conversation_main_namespace("root-a")
    written = service.upsert_request(
        _request(namespace=namespace, content="forget marker FORGET_ME_UNIQUE")
    )
    index = InMemoryRetrievalIndex()
    index.upsert(
        RetrievalDocument(
            collection="focus_memory",
            doc_id=f"memory:{written.memory_id}",
            source_id=written.memory_id,
            text="forget marker FORGET_ME_UNIQUE",
            fields={"namespace": namespace, "status": "active"},
        )
    )
    forgotten = service.forget(memory_id=written.memory_id)
    retriever = MemoryRetriever(repository=repository, retrieval_index=index)
    bundle = retriever.retrieve_for_turn(
        context=context,
        state={},
        query="forget marker",
        prompt_mode=PromptMode.EXPLORE,
    )
    observation = _observation(
        "forgotten-stale-index",
        records=repository.records.values(),
        bundle=bundle,
        context=context,
        expected={
            "active_record_count": 0,
            "selected_memory_ids": [],
            "forgotten_memory_ids": [written.memory_id],
            "forgotten_markers": ["FORGET_ME_UNIQUE"],
        },
    )

    report = evaluate_memory_layer_observation(observation)
    assert forgotten.tombstone_id
    assert report["passed"] is True, report
    assert repository.records[written.memory_id].content == ""


def test_explicit_reassertion_after_forget_is_new_id_not_old_id_resurrection():
    repository = _FakeMemoryRepository()
    service = MemoryService(repository=repository)
    retriever = MemoryRetriever(repository=repository)
    context = RequestContext(user_id="user-a", root_thread_id="root-a")
    request = _request(
        namespace=conversation_main_namespace("root-a"),
        content="forget marker REASSERTED_DECISION",
    )
    old = service.upsert_request(request)
    service.forget(memory_id=old.memory_id)
    new = service.upsert_request(request)
    bundle = retriever.retrieve_for_turn(
        context=context,
        state={},
        query="forget marker",
        prompt_mode=PromptMode.EXPLORE,
    )
    observation = _observation(
        "explicit-reassertion",
        records=repository.records.values(),
        bundle=bundle,
        context=context,
        recreated_record_ids=[new.memory_id],
        expected={
            "active_record_count": 1,
            "selected_memory_ids": [new.memory_id],
            "required_use_markers": ["REASSERTED_DECISION"],
            "forgotten_memory_ids": [old.memory_id],
        },
    )

    report = evaluate_memory_layer_observation(observation)
    assert new.memory_id != old.memory_id
    assert report["recreated_record_ids"] == [new.memory_id]
    assert report["passed"] is True, report


def test_legacy_hydration_excludes_forgotten_marker_but_keeps_active_control(tmp_path):
    store = PersistentInMemoryStore(tmp_path / "memory-store.pkl")
    writer = MemoryWriter(store=store)
    context = RequestContext(user_id="user-a", root_thread_id="root-a")
    namespace = conversation_main_namespace("root-a")
    active_id = writer.write_records(
        [_request(namespace=namespace, content="legacy marker ACTIVE_CONTROL")]
    )[0]
    forgotten_id = writer.write_records(
        [_request(namespace=namespace, content="legacy marker FORGOTTEN_LEGACY")]
    )[0]
    raw = store.get(namespace, forgotten_id)
    payload = dict(raw.value)
    payload.update(
        {
            "status": "forgotten",
            "deleted_at": datetime.now(UTC).isoformat(),
        }
    )
    store.put(namespace, forgotten_id, payload)
    retriever = MemoryRetriever(store=store)
    bundle = retriever.retrieve_for_turn(
        context=context,
        state={},
        query="legacy marker",
        prompt_mode=PromptMode.EXPLORE,
    )
    observation = _observation(
        "legacy-forgotten-hydration",
        records=[store.get(namespace, active_id).value, payload],
        bundle=bundle,
        context=context,
        expected={
            "active_record_count": 1,
            "selected_memory_ids": [active_id],
            "required_use_markers": ["ACTIVE_CONTROL"],
            "forgotten_memory_ids": [forgotten_id],
            "forgotten_markers": ["FORGOTTEN_LEGACY"],
        },
    )

    report = evaluate_memory_layer_observation(observation)
    assert report["passed"] is True, report
    assert bundle.retrieval_plan["source"] == "legacy_store"


def test_layer_evaluator_rejects_empty_and_stale_active_observations():
    assert evaluate_memory_layer_observation({})["passed"] is False
    assert evaluate_memory_layer_suite([])["summary"]["passed"] is False
    report = evaluate_memory_layer_observation(
        {
            "case_id": "stale-active",
            "write": {
                "records": [
                    {
                        "memory_id": "old",
                        "status": "active",
                        "content": "STALE_DECISION",
                        "deleted_at": None,
                    }
                ]
            },
            "retrieval": {"selected_memory_ids": ["old"]},
            "use": {"prompt": "STALE_DECISION", "scoped_prompt": ""},
            "expected": {"stale_decision_markers": ["STALE_DECISION"]},
        }
    )
    assert report["passed"] is False
    assert set(report["layer_failures"]) == {"write", "retrieval", "use"}
    assert len(report["hard_stop_violations"]) == 2


def test_required_use_marker_must_reach_the_scoped_prompt():
    report = evaluate_memory_layer_observation(
        {
            "case_id": "scoped-use",
            "write": {"records": []},
            "retrieval": {"selected_memory_ids": []},
            "use": {"prompt": "CURRENT", "scoped_prompt": ""},
            "expected": {"required_use_markers": ["CURRENT"]},
        }
    )

    assert report["passed"] is False
    assert "missing_required_marker:CURRENT" in report["layer_failures"]["use"]


def test_selected_forgotten_id_is_a_retrieval_hard_stop_even_without_prompt_text():
    report = evaluate_memory_layer_observation(
        {
            "case_id": "forgotten-selected",
            "write": {
                "records": [
                    {
                        "memory_id": "old",
                        "status": "forgotten",
                        "content": "",
                        "deleted_at": "2026-11-22T00:00:00+00:00",
                    }
                ]
            },
            "retrieval": {"selected_memory_ids": ["old"]},
            "use": {"prompt": "", "scoped_prompt": ""},
            "expected": {"forgotten_memory_ids": ["old"]},
        }
    )

    assert report["passed"] is False
    assert "forgotten_memory_selected:old" in report["hard_stop_violations"]
    assert "forgotten_memory_selected:old" in report["layer_failures"]["retrieval"]


def test_malformed_or_vacuous_observations_fail_instead_of_raising_or_passing():
    malformed = evaluate_memory_layer_observation(
        {
            "case_id": "bad",
            "write": ["not-a-mapping"],
            "retrieval": {},
            "use": {},
            "expected": {"selected_memory_ids": []},
        }
    )
    vacuous = evaluate_memory_layer_observation(
        {"case_id": "vacuous", "write": {}, "retrieval": {}, "use": {}}
    )

    assert malformed["passed"] is False
    assert "invalid_observation" in malformed["layer_failures"]["write"]
    assert vacuous["passed"] is False
    assert "invalid_observation" in vacuous["layer_failures"]["write"]
