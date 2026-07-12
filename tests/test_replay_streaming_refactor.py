import asyncio
from pathlib import Path
from types import SimpleNamespace

from focus_agent.api.routers.harness_runs import replay_streaming
from focus_agent.api.routers.harness_runs import replay_streaming_lifecycle as lifecycle
from focus_agent.harness.runtime import RunStatus


def test_replay_streaming_preserves_lifecycle_compatibility_exports_and_line_budget():
    streaming_path = Path(replay_streaming.__file__)

    assert replay_streaming._task_outcome_event_payload is lifecycle._task_outcome_event_payload
    assert replay_streaming._safe_failed_thread_state is lifecycle._safe_failed_thread_state
    assert replay_streaming._is_cancel_cleanup_exception is lifecycle._is_cancel_cleanup_exception
    assert len(streaming_path.read_text(encoding="utf-8").splitlines()) <= 700


def test_lifecycle_helpers_report_failures_and_close_the_stream():
    class _Manager:
        def __init__(self):
            self.record = SimpleNamespace(abort_event=asyncio.Event())
            self.statuses = []

        def get(self, run_id):
            assert run_id == "run-1"
            return self.record

        async def set_status(self, run_id, status, **kwargs):
            self.statuses.append((run_id, status, kwargs))

    async def scenario():
        manager = _Manager()
        runtime = SimpleNamespace(run_manager=manager)
        published = []
        recorded = []
        closed = []

        async def publish(event_name, **data):
            published.append((event_name, data))

        async def close_run_stream(**kwargs):
            closed.append(kwargs)

        interrupted = await lifecycle._handle_stream_exception(
            runtime=runtime,
            chat=SimpleNamespace(),
            run_id="run-1",
            thread_id="thread-1",
            user_id="user-1",
            context=SimpleNamespace(root_thread_id="root-1"),
            branch_meta={"branch": "main"},
            trace_correlation=None,
            publish=publish,
            exc=RuntimeError("stream failed"),
            kind="chat.turn",
            final_payload={"messages": []},
            initial_message_count=0,
            initial_llm_calls=0,
            started_at=0,
            safe_chat_values=lambda **kwargs: {"task_outcome": {"status": "failed"}},
            safe_failed_thread_state=lambda **kwargs: {"thread_id": "thread-1"},
            record_harness_turn=lambda **kwargs: recorded.append(kwargs),
        )
        await lifecycle._close_stream(
            runtime=runtime,
            run_id="run-1",
            thread_id="thread-1",
            sequence=3,
            close_run_stream=close_run_stream,
        )

        assert interrupted is False
        assert manager.statuses == [
            ("run-1", RunStatus.ERROR, {"error": "stream failed"}),
        ]
        assert recorded[0]["status"] == "failed"
        assert recorded[0]["error"] == "stream failed"
        assert published == [
            (
                "run.failed",
                {
                    "error": "RuntimeError",
                    "message": "stream failed",
                    "thread_state": {"thread_id": "thread-1"},
                    "task_outcome": {"status": "failed"},
                },
            )
        ]
        assert closed == [
            {
                "runtime": runtime,
                "run_id": "run-1",
                "thread_id": "thread-1",
                "sequence": 3,
            }
        ]

    asyncio.run(scenario())
