from .support import (
    AIMessage,
    BranchMeta,
    BranchRole,
    ConcurrentTurnError,
    CoordinationBackend,
    FakeGraph,
    InMemoryBackgroundJobDeduperBackend,
    InMemoryRateLimitBackend,
    InMemoryThreadTurnLockBackend,
    Path,
    RecordingGraph,
    Settings,
    SettingsOverlay,
    SimpleNamespace,
    SQLiteBranchRepository,
    StaleBranchMetaGraph,
    ThreadTurnLeaseManager,
    _chat_for_repo,
    _repo_with_child_branch,
    _repo_with_merged_branch,
    pytest,
    threading,
    time,
)


def test_thread_turn_lock_heartbeat_interval_uses_ttl_third_cap(
    chat_service_factory,
):
    runtime = SimpleNamespace(
        settings=SettingsOverlay(
            Settings(runtime_thread_lock_ttl_seconds=9.0),
            runtime_thread_lock_heartbeat_seconds=10.0,
        ),
        graph=FakeGraph(),
        repo=SimpleNamespace(),
    )
    chat = chat_service_factory(runtime)

    assert chat._thread_turn_lock_heartbeat_seconds() == 3.0

    runtime.settings = SettingsOverlay(
        Settings(runtime_thread_lock_ttl_seconds=9.0),
        runtime_thread_lock_heartbeat_seconds=2.0,
    )
    chat = chat_service_factory(runtime)

    assert chat._thread_turn_lock_heartbeat_seconds() == 2.0


def test_send_message_rejects_merged_branch(chat_service_factory, tmp_path: Path):
    chat = _chat_for_repo(chat_service_factory, _repo_with_merged_branch(tmp_path))

    with pytest.raises(PermissionError, match="Merged branches are read-only."):
        chat.send_message(thread_id="child-merged", user_id="owner-1", message="hello")


def test_send_message_rejects_merged_branch_when_graph_meta_is_stale(
    chat_service_factory, tmp_path: Path
):
    chat = _chat_for_repo(
        chat_service_factory, _repo_with_merged_branch(tmp_path), graph=StaleBranchMetaGraph()
    )

    with pytest.raises(PermissionError, match="Merged branches are read-only."):
        chat.send_message(thread_id="child-merged", user_id="owner-1", message="hello")


def test_branch_title_refresh_uses_durable_background_jobs_when_enabled(
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

    class RecordingBranchService:
        def __init__(self):
            self.calls: list[tuple[str, dict[str, str]]] = []

        def refresh_conversation_title_after_first_turn(self, **kwargs):
            self.calls.append(("conversation_title", kwargs))

        def refresh_branch_metadata_after_first_turn(self, **kwargs):
            self.calls.append(("branch_title", kwargs))

    job_deduper = RecordingJobDeduper()
    background_work = RecordingBackgroundWork()
    branch_service = RecordingBranchService()
    runtime = SimpleNamespace(
        settings=Settings(background_job_execution="durable"),
        graph=FakeGraph(),
        repo=repo,
        branch_service=branch_service,
        background_work=background_work,
        coordination_backend=CoordinationBackend(
            thread_turns=InMemoryThreadTurnLockBackend(),
            job_deduper=job_deduper,
            rate_limiter=InMemoryRateLimitBackend(),
        ),
    )
    chat = chat_service_factory(runtime)

    chat._schedule_branch_name_refresh_after_first_turn(
        thread_id="root-1",
        user_id="owner-1",
        branch_meta=None,
        kind="chat.turn",
    )
    chat._schedule_branch_name_refresh_after_first_turn(
        thread_id="child-1",
        user_id="owner-1",
        branch_meta=BranchMeta(
            branch_id="branch-1",
            root_thread_id="root-1",
            parent_thread_id="root-1",
            return_thread_id="root-1",
            branch_name="Deep Dive",
            branch_role=BranchRole.DEEP_DIVE,
            branch_depth=1,
        ),
        kind="chat.turn",
    )
    chat._schedule_branch_name_refresh_after_first_turn(
        thread_id="root-resume",
        user_id="owner-1",
        branch_meta=None,
        kind="chat.resume",
    )
    chat._schedule_branch_name_refresh_after_first_turn(
        thread_id="child-resume",
        user_id="owner-1",
        branch_meta=BranchMeta(
            branch_id="branch-resume",
            root_thread_id="root-resume",
            parent_thread_id="root-resume",
            return_thread_id="root-resume",
            branch_name="Resume Deep Dive",
            branch_role=BranchRole.DEEP_DIVE,
            branch_depth=1,
        ),
        kind="chat.resume",
    )

    assert branch_service.calls == []
    assert background_work.submitted == []
    assert [(spec.kind, spec.key, spec.payload) for spec in job_deduper.enqueued] == [
        (
            "conversation_title",
            "chat:conversation_title:root-1",
            {"root_thread_id": "root-1", "user_id": "owner-1"},
        ),
        (
            "branch_title",
            "chat:branch_title:child-1",
            {"child_thread_id": "child-1", "user_id": "owner-1"},
        ),
        (
            "conversation_title",
            "chat:conversation_title:root-resume",
            {"root_thread_id": "root-resume", "user_id": "owner-1"},
        ),
        (
            "branch_title",
            "chat:branch_title:child-resume",
            {"child_thread_id": "child-resume", "user_id": "owner-1"},
        ),
    ]
    assert all(spec.max_attempts == 3 for spec in job_deduper.enqueued)
    assert all(spec.dedupe_policy == "replace" for spec in job_deduper.enqueued)


def test_branch_metadata_refresh_is_scheduled_after_sync_turn_lease_release(
    chat_service_factory, tmp_path: Path
):
    repo = _repo_with_child_branch(tmp_path)
    locks = InMemoryThreadTurnLockBackend()

    class ImmediateBackgroundWork:
        def __init__(self):
            self.submitted: list[str] = []

        def submit(self, *, key, func, delay_seconds=0.0, **kwargs):
            del delay_seconds
            self.submitted.append(key)
            func(**kwargs)
            return True

    class LeaseCheckingBranchService:
        def __init__(self):
            self.calls: list[dict[str, str]] = []

        def refresh_branch_metadata_after_first_turn(self, **kwargs):
            with ThreadTurnLeaseManager(
                backend=locks,
                thread_id=kwargs["child_thread_id"],
                ttl_seconds=30.0,
                heartbeat_interval_seconds=30.0,
            ):
                self.calls.append(dict(kwargs))

    background_work = ImmediateBackgroundWork()
    branch_service = LeaseCheckingBranchService()
    runtime = SimpleNamespace(
        settings=Settings(),
        graph=RecordingGraph(),
        repo=repo,
        branch_service=branch_service,
        background_work=background_work,
        coordination_backend=CoordinationBackend(
            thread_turns=locks,
            job_deduper=InMemoryBackgroundJobDeduperBackend(),
            rate_limiter=InMemoryRateLimitBackend(),
        ),
    )
    chat = chat_service_factory(runtime)

    chat.send_message(thread_id="child-1", user_id="owner-1", message="first branch turn")

    assert background_work.submitted[-1] == "chat:branch_title:child-1"
    assert branch_service.calls == [{"child_thread_id": "child-1", "user_id": "owner-1"}]


def test_direct_root_turn_bootstraps_conversation_for_ai_title_refresh(
    chat_service_factory, tmp_path: Path
):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))

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
            repo.update_conversation_title(
                root_thread_id=kwargs["root_thread_id"],
                owner_user_id=kwargs["user_id"],
                title="Direct First Turn",
                title_pending_ai=False,
            )

    branch_service = RecordingBranchService()
    runtime = SimpleNamespace(
        settings=Settings(),
        graph=RecordingGraph(),
        repo=repo,
        branch_service=branch_service,
        background_work=ImmediateBackgroundWork(),
    )
    chat = chat_service_factory(runtime)

    chat.send_message(thread_id="root-1", user_id="owner-1", message="Plan the launch")

    record = repo.get_conversation("root-1")
    assert record.title == "Direct First Turn"
    assert record.title_pending_ai is False
    assert branch_service.calls == [{"root_thread_id": "root-1", "user_id": "owner-1"}]


def test_send_message_rejects_concurrent_turn_on_same_thread(chat_service_factory, tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    class BlockingInvokeGraph:
        def __init__(self):
            self.values = {
                "messages": [AIMessage(content="done")],
                "selected_model": "openai:gpt-4.1-mini",
                "selected_thinking_mode": "disabled",
            }
            self.entered = threading.Event()
            self.release = threading.Event()

        def invoke(self, payload, *, config, context, version):
            del payload, config, context, version
            self.entered.set()
            assert self.release.wait(timeout=2.0)
            return {}

        def get_state(self, _config):
            return SimpleNamespace(values=self.values, interrupts=[])

    graph = BlockingInvokeGraph()
    runtime = SimpleNamespace(
        settings=Settings(),
        graph=graph,
        repo=repo,
    )
    chat = chat_service_factory(runtime)
    completed = threading.Event()

    def run_first_turn():
        try:
            chat.send_message(thread_id="root-1", user_id="owner-1", message="first")
        finally:
            completed.set()

    worker = threading.Thread(target=run_first_turn, daemon=True)
    worker.start()
    assert graph.entered.wait(timeout=2.0)

    with pytest.raises(ConcurrentTurnError, match="still processing the previous turn"):
        chat.send_message(thread_id="root-1", user_id="owner-1", message="second")

    graph.release.set()
    assert completed.wait(timeout=2.0)
    worker.join(timeout=2.0)


def test_send_message_skips_post_turn_side_effects_when_thread_turn_heartbeat_is_lost(
    chat_service_factory,
    tmp_path: Path,
):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    class LosingThreadLocks:
        def __init__(self):
            self.acquired: list[tuple[str, str, float]] = []
            self.heartbeats: list[tuple[str, str, float]] = []
            self.released: list[tuple[str, str]] = []

        def acquire_thread_turn(self, *, thread_id: str, owner: str, ttl_seconds: float) -> bool:
            self.acquired.append((thread_id, owner, ttl_seconds))
            return True

        def heartbeat_thread_turn(self, *, thread_id: str, owner: str, ttl_seconds: float) -> bool:
            self.heartbeats.append((thread_id, owner, ttl_seconds))
            return False

        def release_thread_turn(self, *, thread_id: str, owner: str) -> None:
            self.released.append((thread_id, owner))

    class SlowInvokeGraph:
        def __init__(self):
            self.values = {}

        def invoke(self, payload, *, config, context, version):
            del config, context, version
            time.sleep(0.03)
            self.values = {
                "messages": [payload["messages"][-1], AIMessage(content="done")],
                "selected_model": payload["selected_model"],
                "selected_thinking_mode": payload["selected_thinking_mode"],
            }
            return {}

        def get_state(self, _config):
            return SimpleNamespace(values=self.values, interrupts=[])

    class RecordingBackgroundWork:
        def __init__(self):
            self.submitted: list[str] = []

        def submit(self, *, key, func, delay_seconds=0.0, **kwargs):
            del func, delay_seconds, kwargs
            self.submitted.append(key)
            return True

        def release_job_key(self, key: str) -> None:
            del key

    locks = LosingThreadLocks()
    background_work = RecordingBackgroundWork()
    runtime = SimpleNamespace(
        settings=SettingsOverlay(
            Settings(runtime_thread_lock_ttl_seconds=9.0),
            runtime_thread_lock_heartbeat_seconds=0.01,
        ),
        graph=SlowInvokeGraph(),
        repo=repo,
        background_work=background_work,
        coordination_backend=CoordinationBackend(
            thread_turns=locks,
            job_deduper=InMemoryBackgroundJobDeduperBackend(),
            rate_limiter=InMemoryRateLimitBackend(),
        ),
    )
    chat = chat_service_factory(runtime)

    with pytest.raises(ConcurrentTurnError, match="heartbeat was lost"):
        chat.send_message(thread_id="root-1", user_id="owner-1", message="hello")

    assert locks.heartbeats
    assert background_work.submitted == []
    assert locks.released == [("root-1", locks.acquired[0][1])]


class _CloseRecordingBackgroundWork:
    def __init__(self):
        self.close_calls = 0

    def submit(self, *, key, func, delay_seconds=0.0, **kwargs):
        del key, func, delay_seconds, kwargs
        return True

    def close(self) -> bool:
        self.close_calls += 1
        return True


def test_close_closes_owned_background_work_and_is_idempotent(chat_service_factory, monkeypatch):
    background_work = _CloseRecordingBackgroundWork()
    monkeypatch.setattr(
        "focus_agent.services.background_work.BoundedBackgroundQueue",
        lambda **kwargs: background_work,
    )
    chat = chat_service_factory(
        SimpleNamespace(settings=Settings(), graph=FakeGraph(), repo=SimpleNamespace())
    )
    assert chat._submit_background_work(key="work", func=lambda: None) is True

    assert chat.close() is True
    assert chat.close() is True

    assert background_work.close_calls == 2


def test_close_does_not_close_injected_background_work(chat_service_factory):
    background_work = _CloseRecordingBackgroundWork()
    chat = chat_service_factory(
        SimpleNamespace(
            settings=Settings(),
            graph=FakeGraph(),
            repo=SimpleNamespace(),
            background_work=background_work,
        )
    )

    assert chat.close() is True
    assert chat.close() is True

    assert background_work.close_calls == 0
