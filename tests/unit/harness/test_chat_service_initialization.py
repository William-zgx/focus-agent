import asyncio
from types import SimpleNamespace

import pytest

from focus_agent.api import deps


def _request():
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=SimpleNamespace())))


def test_concurrent_lazy_chat_service_initialization_publishes_one_instance(monkeypatch):
    instances = []

    class ChatService:
        def __init__(self, ports):
            self.ports = ports
            self.closed = False
            instances.append(self)

        def close(self):
            self.closed = True

    async def start(_runtime, _chat_service):
        await asyncio.sleep(0.01)

    monkeypatch.setattr(deps, "ChatService", ChatService)
    monkeypatch.setattr(deps.ChatServicePorts, "from_runtime", lambda _runtime: object())
    monkeypatch.setattr(deps, "_start_durable_background_worker", start)
    request = _request()

    async def scenario():
        services = await asyncio.gather(*(deps._ensure_chat_service(request) for _ in range(5)))
        assert len(instances) == 1
        assert services == [instances[0]] * 5
        assert request.app.state.chat_service is instances[0]
        assert instances[0].closed is False

    asyncio.run(scenario())


def test_failed_chat_service_initialization_closes_candidate_and_retries(monkeypatch):
    instances = []
    starts = 0

    class ChatService:
        def __init__(self, ports):
            self.ports = ports
            self.closed = False
            instances.append(self)

        def close(self):
            self.closed = True

    async def start(_runtime, _chat_service):
        nonlocal starts
        starts += 1
        if starts == 1:
            raise RuntimeError("temporary hydration failure")

    monkeypatch.setattr(deps, "ChatService", ChatService)
    monkeypatch.setattr(deps.ChatServicePorts, "from_runtime", lambda _runtime: object())
    monkeypatch.setattr(deps, "_start_durable_background_worker", start)
    request = _request()

    async def scenario():
        with pytest.raises(RuntimeError, match="temporary hydration failure"):
            await deps._ensure_chat_service(request)
        assert instances[0].closed is True
        assert not hasattr(request.app.state, "chat_service")

        service = await deps._ensure_chat_service(request)
        assert service is instances[1]
        assert request.app.state.chat_service is service

    asyncio.run(scenario())
