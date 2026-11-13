from .support import (
    AIMessage,
    CoordinationBackend,
    FakeGraph,
    HumanMessage,
    InMemoryBackgroundJobDeduperBackend,
    InMemoryRateLimitBackend,
    InMemoryThreadTurnLockBackend,
    Path,
    Settings,
    SettingsOverlay,
    SimpleNamespace,
    SQLiteBranchRepository,
    _chat_for_repo,
    _repo_with_merged_branch,
    pytest,
    time,
)


def test_compact_thread_context_rejects_merged_branch(chat_service_factory, tmp_path: Path):
    chat = _chat_for_repo(chat_service_factory, _repo_with_merged_branch(tmp_path))

    with pytest.raises(PermissionError, match="Merged branches are read-only."):
        chat.compact_thread_context(thread_id="child-merged", user_id="owner-1")


def test_preview_thread_context_increases_with_draft_message(chat_service_factory, tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    class ContextPreviewGraph:
        def get_state(self, _config):
            return SimpleNamespace(
                values={
                    "messages": [
                        HumanMessage(content="Known context"),
                        AIMessage(content="Known answer"),
                    ],
                    "context_budget": {"prompt_token_limit": 10000, "chars_per_token": 4},
                },
                interrupts=[],
            )

    runtime = SimpleNamespace(
        settings=Settings(),
        graph=ContextPreviewGraph(),
        repo=repo,
    )
    chat = chat_service_factory(runtime)

    baseline = chat.preview_thread_context(thread_id="root-1", user_id="owner-1")["context_usage"]
    with_draft = chat.preview_thread_context(
        thread_id="root-1",
        user_id="owner-1",
        draft_message="draft context " * 80,
    )["context_usage"]

    assert with_draft["used_tokens"] > baseline["used_tokens"]
    assert with_draft["token_limit"] == 5904


def test_compact_thread_context_updates_summary_without_deleting_messages(
    chat_service_factory, tmp_path: Path
):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    class CompactGraph:
        def __init__(self):
            self.values = {
                "messages": [
                    HumanMessage(content="Original user goal"),
                    AIMessage(content="Original assistant answer"),
                ],
                "rolling_summary": "Previous rolling summary.",
                "user_constraints": [
                    {"constraint": "Keep token usage separate from context usage."}
                ],
                "artifacts": [
                    {
                        "title": "Context usage decision",
                        "uri": "artifact://context/usage-decision",
                    }
                ],
                "context_budget": {"prompt_token_limit": 10000, "chars_per_token": 4},
            }
            self.updates = []

        def get_state(self, _config):
            return SimpleNamespace(values=self.values, interrupts=[])

        def update_state(self, _config, values, as_node=None):
            self.updates.append((values, as_node))
            self.values = {**self.values, **dict(values)}

    graph = CompactGraph()
    runtime = SimpleNamespace(
        settings=Settings(),
        graph=graph,
        repo=repo,
    )
    chat = chat_service_factory(runtime)

    payload = chat.compact_thread_context(thread_id="root-1", user_id="owner-1", trigger="manual")

    assert len(graph.values["messages"]) == 2
    assert graph.updates[-1][1] is None
    assert graph.values["context_compaction"]["trigger"] == "manual"
    assert graph.values["context_compaction"]["non_destructive"] is True
    drift_report = graph.values["context_compaction"]["context_compaction_drift_report"]
    assert set(drift_report) >= {
        "recall",
        "precision",
        "grounding",
        "answerability",
        "overall_drift",
    }
    assert drift_report["drift_risk"] in {"low", "medium", "high"}
    assert "Context compaction snapshot:" in graph.values["rolling_summary"]
    assert "artifact://context/usage-decision" in graph.values["rolling_summary"]
    assert (
        payload["context_usage"]["last_compacted_at"]
        == graph.values["context_compaction"]["last_compacted_at"]
    )


def test_compact_thread_context_heartbeats_thread_turn_lock(chat_service_factory, tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    class RecordingThreadLocks:
        def __init__(self):
            self.acquired: list[tuple[str, str, float]] = []
            self.heartbeats: list[tuple[str, str, float]] = []
            self.released: list[tuple[str, str]] = []

        def acquire_thread_turn(self, *, thread_id: str, owner: str, ttl_seconds: float) -> bool:
            self.acquired.append((thread_id, owner, ttl_seconds))
            return True

        def heartbeat_thread_turn(self, *, thread_id: str, owner: str, ttl_seconds: float) -> bool:
            self.heartbeats.append((thread_id, owner, ttl_seconds))
            return True

        def release_thread_turn(self, *, thread_id: str, owner: str) -> None:
            self.released.append((thread_id, owner))

    class SlowCompactGraph:
        def __init__(self):
            self.values = {
                "messages": [
                    HumanMessage(content="Original user goal"),
                    AIMessage(content="Original assistant answer"),
                ],
                "context_budget": {"prompt_token_limit": 10000, "chars_per_token": 4},
            }

        def get_state(self, _config):
            return SimpleNamespace(values=self.values, interrupts=[])

        def update_state(self, _config, values, as_node=None):
            del _config, as_node
            time.sleep(0.03)
            self.values = {**self.values, **dict(values)}

    locks = RecordingThreadLocks()
    runtime = SimpleNamespace(
        settings=SettingsOverlay(
            Settings(runtime_thread_lock_ttl_seconds=9.0),
            runtime_thread_lock_heartbeat_seconds=0.01,
        ),
        graph=SlowCompactGraph(),
        repo=repo,
        coordination_backend=CoordinationBackend(
            thread_turns=locks,
            job_deduper=InMemoryBackgroundJobDeduperBackend(),
            rate_limiter=InMemoryRateLimitBackend(),
        ),
    )
    chat = chat_service_factory(runtime)

    chat.compact_thread_context(thread_id="root-1", user_id="owner-1", trigger="manual")

    assert locks.acquired
    assert locks.heartbeats
    assert locks.heartbeats[0][2] == 9.0
    assert locks.released == [("root-1", locks.acquired[0][1])]


def test_post_turn_context_compaction_uses_durable_background_job_when_enabled(
    chat_service_factory, tmp_path: Path
):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    class RecordingJobDeduper(InMemoryBackgroundJobDeduperBackend):
        def __init__(self):
            super().__init__()
            self.enqueued = []

        def enqueue_job(self, spec):
            self.enqueued.append(spec)
            return True

    class RecordingBackgroundWork:
        def __init__(self):
            self.submitted: list[str] = []

        def submit(self, *, key, func, delay_seconds=0.0, **kwargs):
            del func, delay_seconds, kwargs
            self.submitted.append(key)
            return True

    job_deduper = RecordingJobDeduper()
    background_work = RecordingBackgroundWork()
    runtime = SimpleNamespace(
        settings=Settings(background_job_execution="durable"),
        graph=FakeGraph(),
        repo=repo,
        background_work=background_work,
        coordination_backend=CoordinationBackend(
            thread_turns=InMemoryThreadTurnLockBackend(),
            job_deduper=job_deduper,
            rate_limiter=InMemoryRateLimitBackend(),
        ),
    )
    chat = chat_service_factory(runtime)

    chat._schedule_post_turn_context_compaction(
        thread_id="root-1", user_id="owner-1", kind="chat.turn"
    )
    chat._schedule_post_turn_context_compaction(
        thread_id="root-2", user_id="owner-1", kind="chat.resume"
    )

    assert background_work.submitted == []
    assert [(spec.kind, spec.key, spec.payload) for spec in job_deduper.enqueued] == [
        (
            "context_compaction",
            "chat:context_compaction:root-1",
            {
                "thread_id": "root-1",
                "user_id": "owner-1",
                "trigger": "auto_post_turn",
                "force": False,
            },
        ),
        (
            "context_compaction",
            "chat:context_compaction:root-2",
            {
                "thread_id": "root-2",
                "user_id": "owner-1",
                "trigger": "auto_post_turn",
                "force": False,
            },
        ),
    ]
    assert all(spec.max_attempts == 3 for spec in job_deduper.enqueued)
    assert all(spec.dedupe_policy == "replace" for spec in job_deduper.enqueued)
