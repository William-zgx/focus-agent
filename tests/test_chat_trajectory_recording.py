from __future__ import annotations

import logging
from types import SimpleNamespace

from focus_agent.retrieval import trajectory as retrieval_trajectory
from focus_agent.services.chat import trajectory_recording
from focus_agent.services.chat.threads import (
    record_turn_trajectory_best_effort as legacy_record_turn_trajectory_best_effort,
)


def _recording_kwargs() -> dict[str, object]:
    return {
        "settings": SimpleNamespace(
            trajectory_observation_max_chars=123,
            trajectory_answer_max_chars=456,
            trajectory_hash_user_id=True,
        ),
        "thread_id": "thread-1",
        "user_id": "user-1",
        "root_thread_id": "root-1",
        "kind": "chat.turn",
        "status": "success",
        "final_values": {"messages": []},
        "initial_message_count": 2,
        "initial_llm_calls": 3,
        "started_at": object(),
        "finished_at": object(),
        "branch_meta": None,
    }


def test_threads_reexports_trajectory_recording_function() -> None:
    assert (
        legacy_record_turn_trajectory_best_effort
        is trajectory_recording.record_turn_trajectory_best_effort
    )


def test_record_turn_trajectory_persists_and_indexes(monkeypatch) -> None:
    record = object()
    build_calls: list[dict[str, object]] = []
    recorded: list[object] = []
    index_calls: list[dict[str, object]] = []

    def build_record(**kwargs):
        build_calls.append(kwargs)
        return record

    class Recorder:
        def record_turn(self, value) -> None:
            recorded.append(value)

    monkeypatch.setattr(trajectory_recording, "build_turn_trajectory_record", build_record)
    monkeypatch.setattr(
        retrieval_trajectory,
        "index_trajectory_record",
        lambda **kwargs: index_calls.append(kwargs),
    )

    trajectory_recording.record_turn_trajectory_best_effort(
        recorder=Recorder(),
        retrieval_index="retrieval-index",
        embedding_provider="embedding-provider",
        **_recording_kwargs(),
    )

    assert recorded == [record]
    assert index_calls == [
        {
            "retrieval_index": "retrieval-index",
            "embedding_provider": "embedding-provider",
            "record": record,
        }
    ]
    assert build_calls[0]["thread_id"] == "thread-1"
    assert build_calls[0]["observation_max_chars"] == 123
    assert build_calls[0]["answer_max_chars"] == 456
    assert build_calls[0]["hash_user_id"] is True


def test_record_turn_trajectory_swallows_recorder_failure(
    monkeypatch,
    caplog,
) -> None:
    class BrokenRecorder:
        def record_turn(self, record) -> None:
            del record
            raise RuntimeError("postgres unavailable")

    monkeypatch.setattr(
        trajectory_recording,
        "build_turn_trajectory_record",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        retrieval_trajectory,
        "index_trajectory_record",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("indexing should not run")),
    )

    with caplog.at_level(logging.WARNING, logger="focus_agent.chat"):
        trajectory_recording.record_turn_trajectory_best_effort(
            recorder=BrokenRecorder(),
            **_recording_kwargs(),
        )

    assert "failed to persist turn trajectory" in caplog.text
    assert "failed to index turn trajectory" not in caplog.text


def test_record_turn_trajectory_swallows_index_failure(
    monkeypatch,
    caplog,
) -> None:
    recorded: list[object] = []
    record = object()

    class Recorder:
        def record_turn(self, value) -> None:
            recorded.append(value)

    monkeypatch.setattr(
        trajectory_recording,
        "build_turn_trajectory_record",
        lambda **_kwargs: record,
    )
    monkeypatch.setattr(
        retrieval_trajectory,
        "index_trajectory_record",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("index unavailable")),
    )

    with caplog.at_level(logging.WARNING, logger="focus_agent.chat"):
        trajectory_recording.record_turn_trajectory_best_effort(
            recorder=Recorder(),
            **_recording_kwargs(),
        )

    assert recorded == [record]
    assert "failed to index turn trajectory" in caplog.text
    assert "failed to persist turn trajectory" not in caplog.text
