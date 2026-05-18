"""Persistent agent-to-agent progress and directive messages."""

from __future__ import annotations

import threading
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha1
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .contracts import AgentMessage, AgentMessageType


class InMemoryAgentMessageBus:
    """Durable-enough local message bus with TTL and ACK semantics."""

    def __init__(self, *, default_ttl_seconds: float = 300.0) -> None:
        self.default_ttl_seconds = max(float(default_ttl_seconds or 0.0), 0.0)
        self._lock = threading.Lock()
        self._messages: dict[str, AgentMessage] = {}

    def publish(
        self,
        *,
        session_id: str,
        source_agent: str,
        target_agent: str | None,
        message_type: AgentMessageType,
        payload: dict[str, Any],
    ) -> str:
        now = time.monotonic()
        resolved_type = AgentMessageType(message_type)
        expires_at = (
            None if resolved_type == AgentMessageType.DIRECTIVE else now + self.default_ttl_seconds
        )
        message = AgentMessage(
            message_id=uuid4().hex,
            session_id=str(session_id),
            source_agent=str(source_agent),
            target_agent=str(target_agent) if target_agent else None,
            message_type=resolved_type,
            payload=dict(payload or {}),
            created_at=now,
            expires_at=expires_at,
        )
        with self._lock:
            self._messages[message.message_id] = message
        return message.message_id

    def subscribe(self, *, session_id: str, agent_id: str) -> InMemoryMessageStream:
        return InMemoryMessageStream(self, session_id=str(session_id), agent_id=str(agent_id))

    def _poll(self, *, session_id: str, agent_id: str) -> list[AgentMessage]:
        now = time.monotonic()
        with self._lock:
            self._drop_expired(now)
            return [
                message
                for message in sorted(self._messages.values(), key=lambda item: item.created_at)
                if message.session_id == session_id
                and message.acked_at is None
                and (message.target_agent is None or message.target_agent == agent_id)
            ]

    def _ack(self, message_id: str) -> None:
        now = time.monotonic()
        with self._lock:
            message = self._messages.get(message_id)
            if message is not None:
                self._messages[message_id] = replace(message, acked_at=now)

    def cleanup_expired(self) -> int:
        with self._lock:
            return self._drop_expired(time.monotonic())

    def _drop_expired(self, now: float) -> int:
        expired = [
            message_id
            for message_id, message in self._messages.items()
            if message.expires_at is not None and message.expires_at <= now
        ]
        for message_id in expired:
            self._messages.pop(message_id, None)
        return len(expired)


class InMemoryMessageStream:
    def __init__(self, bus: InMemoryAgentMessageBus, *, session_id: str, agent_id: str) -> None:
        self._bus = bus
        self._session_id = session_id
        self._agent_id = agent_id

    def poll(self) -> list[AgentMessage]:
        return self._bus._poll(session_id=self._session_id, agent_id=self._agent_id)

    def ack(self, message_id: str) -> None:
        self._bus._ack(message_id)

    def __iter__(self):
        return iter(self.poll())


class PostgresAgentMessageBus:
    """Postgres message table publisher with NOTIFY and poll/ack streams."""

    def __init__(self, database_uri: str, *, default_ttl_seconds: float = 300.0) -> None:
        self.database_uri = database_uri
        self.default_ttl_seconds = max(float(default_ttl_seconds or 0.0), 0.0)

    def _connect(self):
        return psycopg.connect(self.database_uri, row_factory=dict_row)

    def publish(
        self,
        *,
        session_id: str,
        source_agent: str,
        target_agent: str | None,
        message_type: AgentMessageType,
        payload: dict[str, Any],
    ) -> str:
        message_id = uuid4().hex
        resolved_type = AgentMessageType(message_type)
        expires_at = (
            None
            if resolved_type == AgentMessageType.DIRECTIVE
            else datetime.now(UTC) + timedelta(seconds=self.default_ttl_seconds)
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agent_messages (
                        message_id,
                        session_id,
                        source_agent,
                        target_agent,
                        message_type,
                        payload,
                        created_at,
                        expires_at,
                        acked_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, now(), %s, NULL)
                    """,
                    (
                        message_id,
                        str(session_id),
                        str(source_agent),
                        str(target_agent) if target_agent else None,
                        resolved_type.value,
                        Jsonb(dict(payload or {})),
                        expires_at,
                    ),
                )
                cur.execute(
                    "SELECT pg_notify(%s, %s)",
                    (_channel_for_session(str(session_id)), message_id),
                )
        return message_id

    def subscribe(self, *, session_id: str, agent_id: str) -> PostgresMessageStream:
        return PostgresMessageStream(self, session_id=str(session_id), agent_id=str(agent_id))

    def _poll(self, *, session_id: str, agent_id: str) -> list[AgentMessage]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM agent_messages
                    WHERE expires_at IS NOT NULL AND expires_at <= now()
                    """
                )
                cur.execute(
                    """
                    SELECT message_id, session_id, source_agent, target_agent, message_type,
                           payload, created_at, expires_at, acked_at
                    FROM agent_messages
                    WHERE session_id = %s
                      AND acked_at IS NULL
                      AND (target_agent IS NULL OR target_agent = %s)
                      AND (expires_at IS NULL OR expires_at > now())
                    ORDER BY created_at, message_id
                    """,
                    (session_id, agent_id),
                )
                return [_message_from_row(row) for row in cur.fetchall()]

    def _ack(self, message_id: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE agent_messages
                    SET acked_at = now()
                    WHERE message_id = %s
                    """,
                    (message_id,),
                )

    def cleanup_expired(self) -> int:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM agent_messages
                    WHERE expires_at IS NOT NULL AND expires_at <= now()
                    RETURNING message_id
                    """
                )
                return len(cur.fetchall())


class PostgresMessageStream:
    def __init__(self, bus: PostgresAgentMessageBus, *, session_id: str, agent_id: str) -> None:
        self._bus = bus
        self._session_id = session_id
        self._agent_id = agent_id

    def poll(self) -> list[AgentMessage]:
        return self._bus._poll(session_id=self._session_id, agent_id=self._agent_id)

    def ack(self, message_id: str) -> None:
        self._bus._ack(message_id)

    def __iter__(self):
        return iter(self.poll())


def _channel_for_session(session_id: str) -> str:
    normalized = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in session_id)
    channel = f"agent_msg_{normalized}"
    if len(channel) <= 63:
        return channel
    return f"agent_msg_{sha1(session_id.encode('utf-8')).hexdigest()[:24]}"


def _message_from_row(row: dict[str, Any]) -> AgentMessage:
    payload = row.get("payload")
    created_at = row.get("created_at")
    expires_at = row.get("expires_at")
    acked_at = row.get("acked_at")
    return AgentMessage(
        message_id=str(row["message_id"]),
        session_id=str(row["session_id"]),
        source_agent=str(row["source_agent"]),
        target_agent=str(row["target_agent"]) if row.get("target_agent") else None,
        message_type=AgentMessageType(str(row["message_type"])),
        payload=dict(payload) if isinstance(payload, dict) else {},
        created_at=created_at.timestamp() if isinstance(created_at, datetime) else 0.0,
        expires_at=expires_at.timestamp() if isinstance(expires_at, datetime) else None,
        acked_at=acked_at.timestamp() if isinstance(acked_at, datetime) else None,
    )


__all__ = [
    "InMemoryAgentMessageBus",
    "InMemoryMessageStream",
    "PostgresAgentMessageBus",
    "PostgresMessageStream",
]
