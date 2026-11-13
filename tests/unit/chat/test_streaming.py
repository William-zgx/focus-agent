from focus_agent.services.chat import ChatService

from .support import (
    AIMessage,
    HumanMessage,
    Path,
    Settings,
    SimpleNamespace,
    SQLiteBranchRepository,
    _produce_run_stream,
    asyncio,
)


def test_sse_frame_serializes_message_objects():
    frame = ChatService._sse_frame(
        event="state.update",
        data={"messages": [HumanMessage(content="hello")]},
    )

    assert "event: state.update" in frame
    assert '"content": "hello"' in frame


def test_stream_harness_run_records_trajectory_and_schedules_title_refresh(
    chat_service_factory, tmp_path: Path
):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    class StreamGraph:
        def __init__(self):
            self.values = {
                "messages": [
                    HumanMessage(content="stream this"),
                    AIMessage(
                        content="streamed done",
                        usage_metadata={"input_tokens": 9, "output_tokens": 4, "total_tokens": 13},
                    ),
                ],
                "llm_calls": 1,
                "task_brief": "stream this",
            }

        def get_state(self, _config):
            return SimpleNamespace(values=self.values, interrupts=[])

    class EmptyHarness:
        async def stream_chunks(self, **_kwargs):
            if False:
                yield {}

    class RecordingRunManager:
        def __init__(self):
            self.record = SimpleNamespace(
                abort_event=asyncio.Event(),
                abort_action="interrupt",
            )
            self.statuses: list[object] = []

        async def set_status(self, _run_id, status, error=None):
            del error
            self.statuses.append(status)

        def get(self, _run_id):
            return self.record

    class RecordingStreamBridge:
        def __init__(self):
            self.events: list[tuple[str, dict[str, object]]] = []
            self.ended = False

        async def publish(self, _run_id, event_name, payload):
            self.events.append((event_name, payload))

        async def publish_end(self, _run_id):
            self.ended = True

    class RecordingTrajectoryRecorder:
        def __init__(self):
            self.records = []

        def record_turn(self, record):
            self.records.append(record)

    class ImmediateBackgroundWork:
        def submit(self, *, key, func, delay_seconds=0.0, **kwargs):
            del key, delay_seconds
            func(**kwargs)
            return True

    class RecordingBranchService:
        def __init__(self):
            self.calls: list[dict[str, str]] = []

        def refresh_conversation_title_after_first_turn(self, **kwargs):
            self.calls.append(dict(kwargs))

    graph = StreamGraph()
    run_manager = RecordingRunManager()
    stream_bridge = RecordingStreamBridge()
    recorder = RecordingTrajectoryRecorder()
    branch_service = RecordingBranchService()
    runtime = SimpleNamespace(
        settings=Settings(context_auto_compaction_enabled=False),
        graph=graph,
        harness=EmptyHarness(),
        checkpointer=None,
        repo=repo,
        run_manager=run_manager,
        stream_bridge=stream_bridge,
        trajectory_recorder=recorder,
        branch_service=branch_service,
        background_work=ImmediateBackgroundWork(),
    )
    chat = chat_service_factory(runtime)

    asyncio.run(
        _produce_run_stream(
            runtime=runtime,
            chat=chat,
            run_id="run-1",
            thread_id="root-1",
            user_id="owner-1",
            payload={"messages": [HumanMessage(content="stream this")]},
            context=SimpleNamespace(root_thread_id="root-1"),
            branch_meta=None,
            initial_values={"messages": [], "llm_calls": 0},
            request_id="req-stream",
            kind="chat.turn",
        )
    )

    assert recorder.records[0].kind == "chat.turn"
    assert recorder.records[0].metrics["total_tokens"] == 13
    assert branch_service.calls == [{"root_thread_id": "root-1", "user_id": "owner-1"}]
    assert any(event_name == "run.completed" for event_name, _ in stream_bridge.events)
    assert stream_bridge.ended is True
