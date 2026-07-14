"""Contract tests for Agent Team chat namespace isolation.

The production transport may use HTTP, a queue, or an in-process adapter. Any
adapter used by real-provider evidence must satisfy this small interface so
messages cannot cross Agent Team session/root-thread boundaries.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Protocol

import pytest


@dataclass(frozen=True)
class AgentTeamChatMessage:
    session_id: str
    root_thread_id: str
    sender_id: str
    content: str


class AgentTeamChatIsolationContract(Protocol):
    """Minimum contract for a chat transport used by Agent Team evidence."""

    def publish(self, message: AgentTeamChatMessage) -> None: ...

    def list_messages(
        self, *, session_id: str, root_thread_id: str
    ) -> list[AgentTeamChatMessage]: ...


class DeterministicFixtureChatTransport:
    """Fixture transport that enforces the contract without a provider."""

    def __init__(self) -> None:
        self._messages: dict[tuple[str, str], list[AgentTeamChatMessage]] = defaultdict(list)

    def publish(self, message: AgentTeamChatMessage) -> None:
        self._messages[(message.session_id, message.root_thread_id)].append(message)

    def list_messages(self, *, session_id: str, root_thread_id: str) -> list[AgentTeamChatMessage]:
        return list(self._messages[(session_id, root_thread_id)])


def _exercise_chat_isolation(transport: AgentTeamChatIsolationContract) -> None:
    transport.publish(
        AgentTeamChatMessage(
            session_id="session-a",
            root_thread_id="root-a",
            sender_id="agent-a",
            content="private to session a",
        )
    )
    transport.publish(
        AgentTeamChatMessage(
            session_id="session-b",
            root_thread_id="root-b",
            sender_id="agent-b",
            content="private to session b",
        )
    )

    session_a_messages = transport.list_messages(session_id="session-a", root_thread_id="root-a")
    session_b_messages = transport.list_messages(session_id="session-b", root_thread_id="root-b")

    assert [message.content for message in session_a_messages] == ["private to session a"]
    assert [message.content for message in session_b_messages] == ["private to session b"]
    assert transport.list_messages(session_id="session-a", root_thread_id="root-b") == []
    assert transport.list_messages(session_id="session-b", root_thread_id="root-a") == []


def test_deterministic_chat_fixture_satisfies_isolation_contract() -> None:
    _exercise_chat_isolation(DeterministicFixtureChatTransport())


@pytest.mark.skip(
    reason=(
        "Real provider chat isolation is disabled by default. Enable only from the "
        "protected/nightly Agent Team Evidence workflow with an approved adapter."
    )
)
def test_real_provider_chat_transport_must_satisfy_isolation_contract() -> None:
    """Reserved evidence hook; never a passing substitute for a real provider check."""

    pytest.fail("Inject the approved real-provider chat transport before enabling this test.")
