from .support import (
    AIMessage,
    Path,
    RecordingGraph,
    Settings,
    SimpleNamespace,
    SQLiteBranchRepository,
    ToolMessage,
    _chat_for_repo,
    _repo_with_child_branch,
)


def test_send_message_records_postgres_trajectory_payload(chat_service_factory, tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    class ToolGraph:
        def __init__(self):
            self.values = {}

        def invoke(self, payload, *, config, context, version):
            del config, context, version
            human = payload["messages"][-1]
            self.values = {
                "messages": [
                    human,
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "id": "tool-1",
                                "name": "read_file",
                                "args": {"path": "README.md"},
                            }
                        ],
                    ),
                    ToolMessage(
                        content="Focus Agent",
                        tool_call_id="tool-1",
                        artifact={
                            "runtime": {
                                "cache_hit": True,
                                "fallback_used": False,
                                "parallel_batch_size": 2,
                            }
                        },
                    ),
                    AIMessage(
                        content="done",
                        response_metadata={
                            "token_usage": {
                                "prompt_tokens": 11,
                                "completion_tokens": 7,
                                "total_tokens": 18,
                            }
                        },
                    ),
                ],
                "llm_calls": 2,
                "task_brief": payload["task_brief"],
                "selected_model": payload["selected_model"],
                "selected_thinking_mode": payload["selected_thinking_mode"],
            }
            return {}

        def get_state(self, _config):
            return SimpleNamespace(values=self.values, interrupts=[])

    class RecordingTrajectoryRecorder:
        def __init__(self):
            self.records = []

        def record_turn(self, record):
            self.records.append(record)

    recorder = RecordingTrajectoryRecorder()
    runtime = SimpleNamespace(
        settings=Settings(
            trajectory_observation_max_chars=20,
            trajectory_answer_max_chars=20,
        ),
        graph=ToolGraph(),
        repo=repo,
        trajectory_recorder=recorder,
    )
    chat = chat_service_factory(runtime)

    payload = chat.send_message(
        thread_id="root-1",
        user_id="owner-1",
        message="read README",
        request_id="req-chat-turn",
    )

    assert len(recorder.records) == 1
    record = recorder.records[0]
    assert payload["trace"]["metadata"]["request_id"] == "req-chat-turn"
    assert payload["trace"]["metadata"]["trace_id"] == record.trace_id
    assert record.kind == "chat.turn"
    assert record.status == "succeeded"
    assert record.thread_id == "root-1"
    assert record.request_id == "req-chat-turn"
    assert record.trace_id
    assert record.root_span_id
    assert record.user_id_hash != "owner-1"
    assert record.user_message == "read README"
    assert record.answer == "done"
    assert [step.tool for step in record.trajectory] == ["read_file"]
    assert record.trajectory[0].cache_hit is True
    assert record.trajectory[0].parallel_batch_size == 2
    assert record.metrics["tool_calls"] == 1
    assert record.metrics["llm_calls"] == 2
    assert record.metrics["input_tokens"] == 11
    assert record.metrics["output_tokens"] == 7
    assert record.metrics["total_tokens"] == 18


def test_send_message_records_child_trajectory_under_resolved_root(
    chat_service_factory, tmp_path: Path
):
    repo = _repo_with_child_branch(tmp_path)

    class ChildGraph:
        def __init__(self):
            self.values_by_thread: dict[str, dict[str, object]] = {}

        @staticmethod
        def _thread_id(config):
            return str((config or {}).get("configurable", {}).get("thread_id") or "")

        def invoke(self, payload, *, config, context, version):
            del version
            thread_id = self._thread_id(config)
            assert thread_id == "child-1"
            assert context.root_thread_id == "root-1"
            self.values_by_thread[thread_id] = {
                "messages": [*list(payload["messages"]), AIMessage(content="child answer")],
                "llm_calls": 1,
                "task_brief": payload["task_brief"],
                "selected_model": payload["selected_model"],
                "selected_thinking_mode": payload["selected_thinking_mode"],
            }
            return {}

        def get_state(self, config):
            return SimpleNamespace(
                values=self.values_by_thread.get(self._thread_id(config), {}),
                interrupts=[],
            )

        def update_state(self, config, values, as_node=None):
            del as_node
            thread_id = self._thread_id(config)
            self.values_by_thread[thread_id] = {
                **self.values_by_thread.get(thread_id, {}),
                **dict(values),
            }

    class RecordingTrajectoryRecorder:
        def __init__(self):
            self.records = []

        def record_turn(self, record):
            self.records.append(record)

    recorder = RecordingTrajectoryRecorder()
    chat = _chat_for_repo(
        chat_service_factory,
        repo,
        graph=ChildGraph(),
        trajectory_recorder=recorder,
    )

    payload = chat.send_message(
        thread_id="child-1",
        user_id="owner-1",
        message="continue on child",
    )

    assert payload["root_thread_id"] == "root-1"
    assert payload["branch_meta"]["branch_id"] == "branch-1"
    assert len(recorder.records) == 1
    record = recorder.records[0]
    assert record.thread_id == "child-1"
    assert record.root_thread_id == "root-1"
    assert record.branch_id == "branch-1"
    assert record.parent_thread_id == "root-1"


def test_trajectory_recorder_failure_does_not_fail_turn(chat_service_factory, tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")
    graph = RecordingGraph()

    class BrokenTrajectoryRecorder:
        def record_turn(self, record):
            del record
            raise RuntimeError("postgres unavailable")

    runtime = SimpleNamespace(
        settings=Settings(),
        graph=graph,
        repo=repo,
        trajectory_recorder=BrokenTrajectoryRecorder(),
    )
    chat = chat_service_factory(runtime)

    payload = chat.send_message(
        thread_id="root-1",
        user_id="owner-1",
        message="hello",
        request_id="req-thread-state",
    )

    assert payload["assistant_message"] == "planned"
    assert payload["trace"]["metadata"]["request_id"] == "req-thread-state"
