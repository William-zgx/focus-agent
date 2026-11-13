from __future__ import annotations

import inspect
import threading
from pathlib import Path
from types import SimpleNamespace

from focus_agent.services.chat import branch_actions, branch_navigation
from focus_agent.services.chat.ports import ChatServicePorts
from focus_agent.services.chat.runtime_coordination import ChatRuntimeCoordinationMixin
from focus_agent.services.chat.service import ChatService


def _chat_service() -> ChatService:
    return ChatService(
        ChatServicePorts(
            settings=SimpleNamespace(
                runtime_thread_lock_ttl_seconds=30.0,
                runtime_thread_lock_heartbeat_seconds=10.0,
            ),
            graph=object(),
            repo=object(),
        )
    )


def test_chat_service_delegates_runtime_coordination_and_keeps_patch_seam(
    monkeypatch,
) -> None:
    service = _chat_service()

    assert issubclass(ChatService, ChatRuntimeCoordinationMixin)
    assert (
        ChatService._thread_turn_lock_heartbeat_seconds
        is ChatRuntimeCoordinationMixin._thread_turn_lock_heartbeat_seconds
    )

    monkeypatch.setattr(
        ChatService,
        "_thread_turn_lock_ttl_seconds",
        lambda _service: 9.0,
    )

    assert service._thread_turn_lock_heartbeat_seconds() == 3.0


def test_chat_service_module_stays_within_service_orchestration_budget() -> None:
    service_path = Path(inspect.getfile(ChatService))

    assert len(service_path.read_text(encoding="utf-8").splitlines()) <= 740


def test_branch_actions_use_canonical_navigation_module() -> None:
    assert (
        branch_actions.execute_branch_action_navigation
        is branch_navigation.execute_branch_action_navigation
    )
    branch_actions_source = Path(inspect.getfile(branch_actions)).read_text(encoding="utf-8")
    assert "from .service import" not in branch_actions_source


def test_close_propagates_owned_background_shutdown_failure() -> None:
    class FailingCloseQueue:
        close_calls = 0

        def close(self) -> bool:
            self.close_calls += 1
            return False

    service = _chat_service()
    queue = FailingCloseQueue()
    service._background_work = queue

    assert service.close() is False
    assert service.close() is False
    assert queue.close_calls == 2


def test_lazy_background_work_is_singleton_and_close_rejects_new_work(monkeypatch) -> None:
    created = []
    first_created = threading.Event()
    second_started = threading.Event()
    release_first = threading.Event()

    class RecordingQueue:
        def __init__(self) -> None:
            self.close_calls = 0

        def submit(self, *, key, func, delay_seconds=0.0, **kwargs):
            del key, func, delay_seconds, kwargs
            return True

        def close(self) -> bool:
            self.close_calls += 1
            return True

    def queue_factory(**kwargs):
        del kwargs
        queue = RecordingQueue()
        created.append(queue)
        if len(created) == 1:
            first_created.set()
            assert release_first.wait(timeout=2.0)
        return queue

    monkeypatch.setattr(
        "focus_agent.services.background_work.BoundedBackgroundQueue",
        queue_factory,
    )
    service = _chat_service()
    results = []

    def first_submit() -> None:
        results.append(service._submit_background_work(key="first", func=lambda: None))

    def second_submit() -> None:
        second_started.set()
        results.append(service._submit_background_work(key="second", func=lambda: None))

    first = threading.Thread(target=first_submit)
    second = threading.Thread(target=second_submit)
    first.start()
    assert first_created.wait(timeout=2.0)
    second.start()
    assert second_started.wait(timeout=2.0)
    release_first.set()
    first.join(timeout=2.0)
    second.join(timeout=2.0)

    assert not first.is_alive()
    assert not second.is_alive()
    assert sorted(results) == [True, True]
    assert len(created) == 1
    assert service.close() is True
    assert created[0].close_calls == 1
    assert service._submit_background_work(key="closed", func=lambda: None) is False
    assert len(created) == 1
