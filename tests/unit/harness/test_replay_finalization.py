import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from langchain.messages import AIMessage

from focus_agent.api.routers.harness_runs.replay_execution import _execute_harness_run
from focus_agent.core.request_context import RequestContext
from focus_agent.harness.runtime import RunManager, RunStatus
from tests.test_harness_api import _collect_produced_events, _event_names, _RecordingFailureChat


class _Chat:
    def __init__(self):
        self.trajectory_calls = []
        self.compaction_calls = 0
        self.branch_refresh_calls = 0

    def _safe_get_values(self, thread_id):
        return {"messages": [], "llm_calls": 0}

    def _context_for_thread(self, thread_id, user_id):
        return None

    def _response_payload(self, **kwargs):
        return {"thread_id": "thread-1", "assistant_message": "done"}

    def _safe_get_interrupts(self, thread_id):
        return []

    def _record_turn_trajectory_best_effort(self, **kwargs):
        self.trajectory_calls.append(kwargs)

    def _schedule_post_turn_context_compaction(self, **kwargs):
        self.compaction_calls += 1

    def _schedule_branch_name_refresh_after_first_turn(self, **kwargs):
        self.branch_refresh_calls += 1


def _runtime(harness):
    return SimpleNamespace(
        settings=SimpleNamespace(model="model-1"),
        harness=harness,
        run_manager=RunManager(),
    )


async def _record(runtime):
    return await runtime.run_manager.create(
        "thread-1",
        user_id="user-1",
        kwargs={"input": {"messages": []}},
    )


async def _execute(runtime, chat, record):
    return await _execute_harness_run(
        runtime=runtime,
        chat=chat,
        run_record=record,
        thread_id="thread-1",
        user_id="user-1",
        message="",
        payload={"messages": []},
        request_id="request-1",
        context=RequestContext(user_id="user-1", root_thread_id="thread-1"),
        branch_meta={"branch": "main"},
        initial_values={"messages": []},
        skip_branch_recommendation=True,
        config={},
    )


def test_execute_harness_run_records_successful_turn_once():
    class Harness:
        def invoke(self, *args, **kwargs):
            return {"messages": [AIMessage(content="done")]}

    async def scenario():
        runtime = _runtime(Harness())
        chat = _Chat()
        record = await _record(runtime)

        response = await _execute(runtime, chat, record)

        assert response.thread_state["thread_id"] == "thread-1"
        assert runtime.run_manager.get(record.run_id).status is RunStatus.SUCCESS
        assert len(chat.trajectory_calls) == 1
        assert chat.trajectory_calls[0]["status"] == "succeeded"
        assert chat.trajectory_calls[0]["kind"] == "chat.turn"
        assert chat.compaction_calls == 1
        assert chat.branch_refresh_calls == 1

    asyncio.run(scenario())


def test_execute_harness_run_records_failed_turn_once():
    class Harness:
        def invoke(self, *args, **kwargs):
            raise RuntimeError("unary graph failed")

    async def scenario():
        runtime = _runtime(Harness())
        chat = _Chat()
        record = await _record(runtime)

        with pytest.raises(RuntimeError, match="unary graph failed"):
            await _execute(runtime, chat, record)

        assert runtime.run_manager.get(record.run_id).status is RunStatus.ERROR
        assert len(chat.trajectory_calls) == 1
        assert chat.trajectory_calls[0]["status"] == "failed"
        assert chat.trajectory_calls[0]["kind"] == "chat.turn"
        assert chat.trajectory_calls[0]["error"] == "unary graph failed"
        assert chat.compaction_calls == 0
        assert chat.branch_refresh_calls == 0

    asyncio.run(scenario())


def test_failure_finalization_preserves_original_error_when_refresh_fails():
    from focus_agent.api.routers.harness_runs.replay_finalization import _HarnessRunFinalizer
    from focus_agent.core.time_utils import utc_now

    class Chat:
        def __init__(self):
            self.recorded = None

        def _context_for_thread(self, thread_id, user_id):
            raise RuntimeError("refresh failed")

        def _safe_get_values(self, thread_id):
            return {"messages": [], "llm_calls": 0}

        def _response_payload(self, **kwargs):
            return {"assistant_message": None}

        def _safe_get_interrupts(self, thread_id):
            return []

        def _record_turn_trajectory_best_effort(self, **kwargs):
            self.recorded = kwargs

    runtime = _runtime(SimpleNamespace())
    record = asyncio.run(_record(runtime))
    chat = Chat()
    finalizer = _HarnessRunFinalizer(
        runtime=runtime,
        chat=chat,
        run_id=record.run_id,
        thread_id=record.thread_id,
        user_id="user-1",
        kind="chat.turn",
        context=RequestContext(user_id="user-1", root_thread_id="thread-1"),
        branch_meta=None,
        trace_correlation=None,
        payload={"messages": []},
        initial_message_count=0,
        initial_llm_calls=0,
        started_at=utc_now(),
    )

    async def scenario():
        await finalizer.fail(TimeoutError("model timeout"), run_status=RunStatus.TIMEOUT)

        assert runtime.run_manager.get(record.run_id).status is RunStatus.TIMEOUT
        assert chat.recorded["status"] == "timeout"
        assert chat.recorded["error"] == "model timeout"

    asyncio.run(scenario())


def test_produce_run_stream_records_successful_turn_once(monkeypatch):
    async def scenario():
        chat = _RecordingFailureChat([AIMessage(content="done")])
        chat._schedule_post_turn_context_compaction = Mock(
            wraps=chat._schedule_post_turn_context_compaction
        )
        chat._schedule_branch_name_refresh_after_first_turn = Mock(
            wraps=chat._schedule_branch_name_refresh_after_first_turn
        )
        events, statuses, ended = await _collect_produced_events(
            monkeypatch,
            [],
            chat=chat,
        )

        assert "run.completed" in _event_names(events)
        assert statuses[-1][0] is RunStatus.SUCCESS
        assert len(chat.trajectory_calls) == 1
        assert chat.trajectory_calls[0]["status"] == "succeeded"
        assert chat.trajectory_calls[0]["kind"] == "chat.turn"
        assert chat.trajectory_calls[0]["answer"] == "done"
        assert chat._schedule_post_turn_context_compaction.call_count == 1
        assert chat._schedule_branch_name_refresh_after_first_turn.call_count == 1
        assert ended is True

    asyncio.run(scenario())
