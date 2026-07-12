from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

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
