from collections.abc import Iterator

import pytest


@pytest.fixture
def chat_service_factory() -> Iterator:
    services = []

    def create_chat_service(*args, **kwargs):
        from focus_agent.services.chat import ChatService

        service = ChatService(*args, **kwargs)
        services.append(service)
        return service

    yield create_chat_service

    close_failures: list[str] = []
    for service in reversed(services):
        try:
            closed = service.close()
        except Exception as exc:
            close_failures.append(f"{service!r}: {exc!r}")
        else:
            if not closed:
                close_failures.append(f"{service!r}: close() returned False")

    assert not close_failures, "ChatService teardown failed: " + "; ".join(close_failures)
